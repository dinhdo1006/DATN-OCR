import os
import re
import json
import time
import logging

import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BUCKET = os.getenv("MINIO_BUCKET", "data-lake")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", 100))

s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
    aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "admin"),
    aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
)

app = FastAPI(title="OCR Test UI")


# =====================================================
# HELPERS
# =====================================================
def natural_key(name: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name or "")]


def list_keys(prefix: str):
    keys, token = [], None
    while True:
        kw = {"Bucket": BUCKET, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kw)
        keys += [o for o in resp.get("Contents", [])]
        if not resp.get("IsTruncated"):
            return keys
        token = resp["NextContinuationToken"]


def exists(key: str) -> bool:
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except ClientError:
        return False


def read_text(key: str) -> str:
    return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read().decode("utf-8")


def doc_status(doc_id: str, uploaded_at=None) -> dict:
    """Suy ra trạng thái từ các object trên MinIO.

    pic/raw/<id>/page_N.png  -> số trang đã preprocess (tổng số trang)
    text/raw/<id>/page_N.txt -> số trang đã OCR xong
    final/<id>/<id>.txt      -> tài liệu đã merge
    """
    pages_total = len(list_keys(f"pic/raw/{doc_id}/"))
    pages_done = len([o for o in list_keys(f"text/raw/{doc_id}/") if o["Key"].endswith(".txt")])
    final = exists(f"final/{doc_id}/{doc_id}.txt")
    merge_status = None
    if final:
        try:
            merge_status = json.loads(read_text(f"final/{doc_id}/{doc_id}.json")).get("status")
        except Exception:
            pass

    if final and merge_status == "partial":
        status = "partial"  # đã ghép nhưng còn trang thiếu box, sẽ tự ghép lại khi box đến
    elif final:
        status = "done"
    elif pages_done > 0:
        status = "ocr"
    elif pages_total > 0:
        status = "layout"
    else:
        status = "queued"

    return {
        "id": doc_id,
        "status": status,
        "pages_total": pages_total,
        "pages_done": pages_done,
        "final": final,
        "uploaded_at": uploaded_at,
    }


# =====================================================
# API
# =====================================================
@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Chỉ nhận file PDF")

    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File vượt quá {MAX_UPLOAD_MB}MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "File không phải PDF hợp lệ")

    stem = re.sub(r"[^\w.-]+", "_", os.path.splitext(os.path.basename(file.filename))[0]).strip("._") or "document"
    # Tên đã tồn tại -> thêm hậu tố thời gian (NiFi ListS3 chỉ nhặt object mới, và tránh trộn kết quả)
    if exists(f"raw/{stem}.pdf") or list_keys(f"final/{stem}/"):
        stem = f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}"

    s3.put_object(Bucket=BUCKET, Key=f"raw/{stem}.pdf", Body=data, ContentType="application/pdf")
    logging.info(f"Uploaded raw/{stem}.pdf ({len(data)} bytes)")
    return {"id": stem, "size": len(data)}


@app.get("/api/documents")
def documents():
    items = []
    for o in list_keys("raw/"):
        key = o["Key"]
        if not key.lower().endswith(".pdf"):
            continue
        doc_id = os.path.splitext(os.path.basename(key))[0]
        items.append(doc_status(doc_id, o["LastModified"].timestamp()))
    items.sort(key=lambda d: d["uploaded_at"] or 0, reverse=True)
    return items


@app.get("/api/documents/{doc_id}")
def document(doc_id: str):
    if "/" in doc_id or ".." in doc_id:
        raise HTTPException(400, "id không hợp lệ")
    info = doc_status(doc_id)

    if info["final"]:
        info["text"] = read_text(f"final/{doc_id}/{doc_id}.txt")
    else:
        # Chưa merge: hiển thị tạm các trang đã OCR xong
        pages = sorted(
            [o["Key"] for o in list_keys(f"text/raw/{doc_id}/") if o["Key"].endswith(".txt")],
            key=natural_key,
        )
        parts = [f"===== PAGE {os.path.splitext(os.path.basename(k))[0]} =====\n{read_text(k).strip()}\n" for k in pages]
        info["text"] = "\n".join(parts)
    return info


@app.get("/api/documents/{doc_id}/download")
def download(doc_id: str):
    key = f"final/{doc_id}/{doc_id}.txt"
    if "/" in doc_id or ".." in doc_id or not exists(key):
        raise HTTPException(404, "Chưa có kết quả cuối cùng")
    return PlainTextResponse(
        read_text(key),
        headers={"Content-Disposition": f'attachment; filename="{doc_id}.txt"'},
    )


@app.get("/api/documents/{doc_path:path}")
def invalid_document_path(doc_path: str):
    # Khai báo sau các route trên nên chỉ nhận đường dẫn còn lại, ví dụ "..%2Fx" được giải mã thành "../x"
    raise HTTPException(400, "id không hợp lệ")


@app.get("/")
def index():
    return FileResponse("static/index.html")
