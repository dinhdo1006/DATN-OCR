import os
import json
import time
import logging
import boto3
from kafka import KafkaConsumer, KafkaProducer
from kafka.structs import OffsetAndMetadata

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Thời gian rảnh (không nhận thêm box) trước khi ghi tạm một trang chưa đủ box.
# Tính theo lần nhận box gần nhất: box có thể xếp hàng lâu ở VietOCR khi tài liệu nhiều trang.
TIMEOUT = int(os.getenv("RECONSTRUCT_TIMEOUT", 120))
# Trang đã ghi tạm được giữ lại để ghép tiếp nếu box đến muộn
EVICT_AFTER = int(os.getenv("RECONSTRUCT_EVICT_AFTER", 3600))
BUCKET = os.getenv("MINIO_BUCKET", "data-lake")

document_buffer = {}

# =========================
# GEOMETRY UTILS
# =========================
def get_center_y(box): return sum(p[1] for p in box) / 4
def get_center_x(box): return sum(p[0] for p in box) / 4
def get_height(box):
    y_coords = [p[1] for p in box]
    return max(y_coords) - min(y_coords)

# Khối ảnh/bảng (ô giả bao cả khối) đứng riêng một dòng, không tham gia gom dòng chữ
BLOCK_TYPES = {"figure", "table"}


def is_block(b):
    return b.get("content_type") in BLOCK_TYPES


def get_top_y(box):
    return min(p[1] for p in box)


def sort_boxes(boxes):
    valid_boxes = [b for b in boxes if b.get("coordinates") and len(b["coordinates"]) == 4]
    return sorted(valid_boxes, key=lambda x: (get_center_y(x['coordinates']), get_center_x(x['coordinates'])))


def group_lines(boxes):
    """Gom box chữ thành dòng theo trục y; khối ảnh/bảng thành dòng riêng.

    Ô bảng (table_cell) chỉ gom với ô cùng bảng, để mỗi dòng là một hàng của bảng.
    """
    text = [b for b in boxes if not is_block(b)]
    blocks = [b for b in boxes if is_block(b)]

    lines = []
    if text:
        # Chỉ lấy chiều cao box chữ: ô giả của ảnh/bảng cao cả khối sẽ làm ngưỡng gom dòng sai
        avg_height = sum(get_height(b['coordinates']) for b in text) / len(text)
        y_threshold = avg_height * 0.5

        current, prev_y = [], None
        for b in text:
            y = get_center_y(b['coordinates'])
            same_table = not current or current[-1].get("table_id") == b.get("table_id")
            if prev_y is None or (abs(y - prev_y) < y_threshold and same_table):
                current.append(b)
            else:
                lines.append(current)
                current = [b]
            prev_y = sum(get_center_y(box['coordinates']) for box in current) / len(current)
        if current:
            lines.append(current)

        for line in lines:
            line.sort(key=lambda x: get_center_x(x['coordinates']))

    # Sắp lại theo trục y: dòng chữ theo tâm, khối theo cạnh trên (nhãn bảng đứng trước các hàng của nó)
    keyed = [(sum(get_center_y(b['coordinates']) for b in line) / len(line), 1, line) for line in lines]
    keyed += [(get_top_y(b['coordinates']) - 1, 0, [b]) for b in blocks]
    keyed.sort(key=lambda t: (t[0], t[1]))
    return [line for _, _, line in keyed]


# =========================
# OUTPUT BUILDERS (văn bản Markdown + JSON)
# =========================
def is_table_row(line):
    return bool(line) and all(b.get("content_type") == "table_cell" for b in line)


def detect_columns(rows):
    """Tìm mép trái các cột: gom mép trái (x_min) của box, giữ cụm xuất hiện ở >= 2 hàng.

    Chữ căn đều bị Paddle tách thành nhiều box trong một ô chỉ xuất hiện ở một hàng
    nên không tạo cột giả.
    """
    xs = [min(p[0] for p in b["coordinates"]) for r in rows for b in r]
    width = max(max(p[0] for p in b["coordinates"]) for r in rows for b in r) - min(xs)
    tol = max(25, 0.02 * width)

    clusters = []  # [x_trung_bình, tập_hàng]
    for x, ri in sorted((min(p[0] for p in b["coordinates"]), ri) for ri, r in enumerate(rows) for b in r):
        if clusters and x - clusters[-1][0] <= tol:
            c = clusters[-1]
            c[0] = (c[0] * c[2] + x) / (c[2] + 1)
            c[1].add(ri)
            c[2] += 1
        else:
            clusters.append([x, {ri}, 1])
    starts = [c[0] for c in clusters if len(c[1]) >= 2]
    return (starts or [min(xs)]), tol


def render_table(rows):
    """Các hàng của một bảng -> bảng Markdown (hàng đầu làm tiêu đề).

    Box được gán vào cột có mép trái gần nhất bên trái nó; hàng trống ở cột đầu
    là dòng tiếp theo của ô nhiều dòng nên được nối vào hàng trước.
    """
    starts, tol = detect_columns(rows)
    ncols = len(starts)

    table = []
    for row in rows:
        cells = [[] for _ in range(ncols)]
        for b in sorted(row, key=lambda b: min(p[0] for p in b["coordinates"])):
            x = min(p[0] for p in b["coordinates"])
            col = max([i for i, s in enumerate(starts) if s <= x + tol] or [0])
            text = (b.get("recognized_text") or "").strip()
            if text:
                cells[col].append(text)
        cells = [" ".join(c) for c in cells]
        if table and not cells[0] and any(cells):
            prev = table[-1]
            for i, c in enumerate(cells):
                if c:
                    prev[i] = f"{prev[i]} {c}".strip()
        elif any(cells):
            table.append(cells)

    out = []
    for i, cells in enumerate(table):
        out.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
        if i == 0:
            out.append("|" + "|".join([" --- "] * ncols) + "|")
    return out


def build_text(lines):
    if not lines:
        return ""

    text_boxes = [b for line in lines for b in line if b.get("coordinates") and not is_block(b)]
    min_x_global = min((min(p[0] for p in b["coordinates"]) for b in text_boxes), default=0)
    CHAR_WIDTH = 45
    out = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Gom các hàng liên tiếp của cùng một bảng -> bảng Markdown
        if is_table_row(line):
            table_id = line[0].get("table_id")
            rows = []
            while i < len(lines) and is_table_row(lines[i]) and lines[i][0].get("table_id") == table_id:
                rows.append(lines[i])
                i += 1
            out += [""] + render_table(rows) + [""]
            continue

        # Khối ảnh/bảng: nhãn tham chiếu tới ảnh đã lưu trong assets/
        if len(line) == 1 and is_block(line[0]):
            out += ["", line[0].get("recognized_text", "")]
            i += 1
            continue

        line_str = ""
        is_title = any(b.get("content_type") == "title" for b in line)
        is_list = any(b.get("content_type") == "list" for b in line)

        for j, b in enumerate(line):
            text = b.get("recognized_text", "")
            if not text:
                continue

            x_min = min(p[0] for p in b["coordinates"])
            if j == 0:
                indent_spaces = int((x_min - min_x_global) / CHAR_WIDTH)
                line_str += " " * max(0, indent_spaces)
            else:
                prev_x_max = max(p[0] for p in line[j - 1]["coordinates"])
                gap_spaces = int((x_min - prev_x_max) / CHAR_WIDTH)
                line_str += " " * max(1, gap_spaces)
            line_str += text

        final_line = line_str.rstrip()
        if not final_line.strip():
            i += 1
            continue

        # Bọc thẻ Markdown tăng tính cấu trúc văn bản
        if is_title:
            out += ["", f"# {final_line.strip()}", ""]
        elif is_list:
            out.append(f"- {final_line.strip()}")
        else:
            out.append(final_line)
        i += 1

    return "\n".join(out).strip("\n") + "\n"


def build_json(image, lines):
    return {
        "source_image": image,
        "processed_at": time.time(),
        "lines": [
            {
                "line_id": i,
                "line_type": line[0].get("content_type", "text") if line else "text",
                "line_text": " ".join(b.get("recognized_text", "") for b in line if b.get("recognized_text")).strip(),
                "elements": [
                    {
                        "box_id": b.get("box_id"),
                        "type": b.get("content_type", "text"),
                        "table_id": b.get("table_id"),
                        "text": b.get("recognized_text", ""),
                        "coordinates": b.get("coordinates"),
                        "s3_asset_url": b.get("s3_key") if b.get("content_type") in ["figure", "table"] else None
                    } for b in line
                ]
            }
            for i, line in enumerate(lines)
        ]
    }


# =========================
# MAIN LOOP
# =========================
def main():
    broker = os.getenv("KAFKA_BROKER", "kafka:9092")
    consumer = KafkaConsumer(
        "ocr-completed",
        bootstrap_servers=[broker],
        group_id="reconstruct-group",
        auto_offset_reset="latest",
        enable_auto_commit=False,
        max_poll_records=100,
        value_deserializer=lambda m: json.loads(m.decode("utf-8"))
    )
    producer = KafkaProducer(
        bootstrap_servers=[broker],
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8")
    )
    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "admin"),
        aws_secret_access_key=os.environ["MINIO_SECRET_KEY"]
    )

    logging.info("Reconstruct worker started...")

    while True:
        msg_pack = consumer.poll(timeout_ms=500)
        offsets = {}

        for tp, msgs in msg_pack.items():
            for msg in msgs:
                try:
                    data = msg.value
                    image = data.get("original_image")
                    box_id = data.get("box_id")
                    total = data.get("total_boxes")

                    if image is None or box_id is None:
                        continue

                    if image not in document_buffer:
                        document_buffer[image] = {
                            "last_seen": time.time(),
                            "dirty": True,
                            "boxes": {},
                            "total_boxes": total,
                            "total_pages": data.get("total_pages"),
                            "document_id": data.get("document_id", "unknown")
                        }

                    buf = document_buffer[image]
                    if buf["total_boxes"] is None and total is not None:
                        buf["total_boxes"] = total
                    if buf.get("total_pages") is None and data.get("total_pages") is not None:
                        buf["total_pages"] = data.get("total_pages")

                    buf["boxes"][box_id] = data
                    buf["last_seen"] = time.time()
                    buf["dirty"] = True
                    offsets[tp] = OffsetAndMetadata(msg.offset + 1, None)
                except Exception as e:
                    logging.error(f"Error parsing message: {e}")

        # Quét dọn RAM buffer định kỳ
        now = time.time()
        for image, buf in list(document_buffer.items()):
            received = len(buf["boxes"])
            total = buf["total_boxes"]
            idle = now - buf["last_seen"]

            # Đã ghi tạm, không có box mới: chỉ dọn RAM sau một thời gian
            if not buf["dirty"]:
                if idle > EVICT_AFTER:
                    del document_buffer[image]
                continue

            is_done = (total is not None) and (received >= total)
            is_timeout = idle > TIMEOUT

            if is_done or is_timeout:
                if is_done:
                    logging.info(f"SUCCESS {image}: Gathered {received}/{total} boxes.")
                else:
                    logging.warning(f"TIMEOUT {image}: Gathered {received}/{total} boxes (sẽ ghép lại nếu box đến muộn).")

                try:
                    boxes = list(buf["boxes"].values())
                    boxes = sort_boxes(boxes)
                    lines = group_lines(boxes)

                    text_content = build_text(lines)
                    json_content = build_json(image, lines)

                    base_name = os.path.splitext(os.path.basename(image))[0]
                    sub_path = os.path.dirname(image).replace("pic/", "", 1)
                    
                    txt_key = f"text/{sub_path}/{base_name}.txt"
                    json_key = f"preprocessed/{sub_path}/{base_name}.json"

                    s3.put_object(Bucket=BUCKET, Key=txt_key, Body=text_content.encode("utf-8"))
                    s3.put_object(Bucket=BUCKET, Key=json_key, Body=json.dumps(json_content, ensure_ascii=False).encode("utf-8"))

                    producer.send(
                        "document-completed",
                        value={
                            "document_id": buf["document_id"],
                            "total_pages": buf.get("total_pages"),
                            "page_name": base_name,
                            "original_image": image,
                            "text_path": txt_key,
                            "json_path": json_key,
                            "status": "success" if is_done else "partial",
                            "boxes_processed": received,
                            "total_boxes": total
                        }
                    )
                    # Giữ lại (kể cả trang đủ box) để box đến muộn / tin nhắn gửi lại không tạo ra trang thiếu
                    buf["dirty"] = False
                except Exception as e:
                    logging.error(f"Error saving reconstruct for {image}: {e}")
                    buf["dirty"] = False

        if offsets:
            consumer.commit(offsets=offsets)
            producer.flush()

if __name__ == "__main__":
    main()