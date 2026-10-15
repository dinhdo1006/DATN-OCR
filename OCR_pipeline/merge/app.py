import os
import re
import json
import time
import logging
import boto3
from kafka import KafkaConsumer, KafkaProducer
from kafka.structs import OffsetAndMetadata

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Thời gian rảnh (không có trang mới) trước khi merge tạm tài liệu chưa đủ trang
TIMEOUT = int(os.getenv("MERGE_TIMEOUT", 180))
# Buffer của tài liệu đã merge tạm được giữ lại để gộp tiếp nếu có trang đến muộn
EVICT_AFTER = int(os.getenv("MERGE_EVICT_AFTER", 3600))
BUCKET = os.getenv("MINIO_BUCKET", "data-lake")

# Buffer theo document_id: gom các trang đã reconstruct xong
document_buffer = {}


def init_s3():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "admin"),
        aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
    )


def read_text(s3, key: str) -> str:
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        return obj["Body"].read().decode("utf-8")
    except Exception as e:
        logging.warning(f"Cannot read {key}: {e}")
        return ""


def natural_key(name: str):
    """page_2 < page_10 (sắp theo số thay vì theo chuỗi)."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name or "")]


def fill_from_storage(s3, buf):
    """Bổ sung các trang đã có trên MinIO nhưng không còn trong buffer
    (merge-worker khởi động lại, hoặc buffer đã bị dọn trước khi một trang được cập nhật muộn)."""
    any_page = next((p for p in buf["pages"].values() if p.get("text_path")), None)
    if not any_page:
        return
    prefix = os.path.dirname(any_page["text_path"]) + "/"
    token = None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kw)
        for o in resp.get("Contents", []):
            key = o["Key"]
            if not key.endswith(".txt"):
                continue
            page_name = os.path.splitext(os.path.basename(key))[0]
            if page_name not in buf["pages"]:
                buf["pages"][page_name] = {
                    "page_name": page_name,
                    "text_path": key,
                    "json_path": "preprocessed/" + key[len("text/"):-len(".txt")] + ".json",
                    "status": "unknown",
                }
        if not resp.get("IsTruncated"):
            return
        token = resp["NextContinuationToken"]


def merge_document(s3, document_id: str, pages: list, status: str) -> dict:
    """Ghép text/json các trang theo thứ tự page_name."""
    pages_sorted = sorted(pages, key=lambda p: natural_key(p.get("page_name", "")))
    merged_parts = []
    md_parts = []
    page_meta = []

    for page in pages_sorted:
        text_path = page.get("text_path")
        json_path = page.get("json_path")
        page_name = page.get("page_name", "unknown")

        text = read_text(s3, text_path) if text_path else ""
        merged_parts.append(f"===== PAGE {page_name} =====\n{text.strip()}\n")
        md_parts.append(f"<!-- {page_name} -->\n\n{text.strip()}\n")
        page_meta.append(
            {
                "page_name": page_name,
                "text_path": text_path,
                "json_path": json_path,
                "status": page.get("status"),
                "boxes_processed": page.get("boxes_processed"),
                "total_boxes": page.get("total_boxes"),
            }
        )

    merged_text = "\n".join(merged_parts).strip() + "\n"
    out_txt = f"final/{document_id}/{document_id}.txt"
    out_json = f"final/{document_id}/{document_id}.json"
    out_md = f"final/{document_id}/{document_id}.md"
    merged_md = "\n---\n\n".join(md_parts).strip() + "\n"

    payload = {
        "document_id": document_id,
        "status": status,
        "page_count": len(pages_sorted),
        "pages": page_meta,
        "merged_at": time.time(),
        "text_path": out_txt,
        "json_path": out_json,
        "markdown_path": out_md,
    }

    s3.put_object(Bucket=BUCKET, Key=out_txt, Body=merged_text.encode("utf-8"))
    s3.put_object(Bucket=BUCKET, Key=out_md, Body=merged_md.encode("utf-8"), ContentType="text/markdown")
    s3.put_object(
        Bucket=BUCKET,
        Key=out_json,
        Body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    return payload


def maybe_flush(s3, producer, document_id: str):
    buf = document_buffer.get(document_id)
    if not buf:
        return

    now = time.time()
    idle = now - buf["last_seen"]

    # Đã merge, không có trang mới/cập nhật: chỉ dọn RAM sau một thời gian.
    # Buffer được giữ lại kể cả khi đủ trang, để trang cập nhật muộn được ghép cùng các trang còn lại.
    if not buf["dirty"]:
        if idle > EVICT_AFTER:
            del document_buffer[document_id]
        return

    try:
        fill_from_storage(s3, buf)
    except Exception as e:
        logging.warning(f"Cannot list pages of {document_id}: {e}")

    received = len(buf["pages"])
    total = buf.get("total_pages")
    complete = total is not None and received >= total
    timed_out = idle > TIMEOUT and received > 0
    if not (complete or timed_out):
        return

    # "success" chỉ khi đủ trang và không trang nào bị ghi tạm do thiếu box
    all_ok = all(p.get("status") in ("success", "unknown") for p in buf["pages"].values())
    status = "success" if complete and all_ok else "partial"
    reason = "complete" if complete else "timeout"
    logging.info(f"MERGE {document_id}: {received}/{total} pages ({reason}, {status})")

    try:
        result = merge_document(s3, document_id, list(buf["pages"].values()), status)
        producer.send("merge-completed", value=result)
        producer.flush()
        logging.info(f"Published merge-completed -> {result['text_path']}")
        buf["dirty"] = False
    except Exception as e:
        logging.exception(f"Merge failed for {document_id}: {e}")


def main():
    broker = os.getenv("KAFKA_BROKER", "kafka:9092")
    s3 = init_s3()

    consumer = KafkaConsumer(
        "document-completed",
        bootstrap_servers=[broker],
        group_id="merge-group",
        auto_offset_reset="latest",
        enable_auto_commit=False,
        max_poll_records=50,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )
    producer = KafkaProducer(
        bootstrap_servers=[broker],
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
    )

    logging.info("Merge worker started...")

    while True:
        packs = consumer.poll(timeout_ms=500)
        offsets = {}

        for tp, msgs in packs.items():
            for msg in msgs:
                try:
                    data = msg.value
                    document_id = data.get("document_id") or "unknown"
                    page_name = data.get("page_name") or data.get("page") or str(time.time())

                    if document_id not in document_buffer:
                        document_buffer[document_id] = {
                            "last_seen": time.time(),
                            "pages": {},
                            "total_pages": None,
                            "dirty": True,
                        }

                    buf = document_buffer[document_id]
                    if buf["total_pages"] is None and data.get("total_pages") is not None:
                        try:
                            buf["total_pages"] = int(data.get("total_pages"))
                        except (TypeError, ValueError):
                            pass

                    buf["pages"][page_name] = data
                    buf["last_seen"] = time.time()
                    buf["dirty"] = True
                    offsets[tp] = OffsetAndMetadata(msg.offset + 1, None)
                except Exception as e:
                    logging.error(f"Parse error: {e}")

        # Flush documents đã đủ trang hoặc timeout
        for document_id in list(document_buffer.keys()):
            maybe_flush(s3, producer, document_id)

        if offsets:
            consumer.commit(offsets=offsets)


if __name__ == "__main__":
    main()
