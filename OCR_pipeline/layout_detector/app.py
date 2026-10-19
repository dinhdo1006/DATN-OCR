import os
import cv2
import json
import time
import boto3
import logging
import numpy as np

# =====================================================
# GIỚI HẠN CPU KHẮT KHE (Nhường tài nguyên cho Docker khác)
# =====================================================
NUM_THREADS = "2"
os.environ["OMP_NUM_THREADS"] = NUM_THREADS
os.environ["MKL_NUM_THREADS"] = NUM_THREADS
os.environ["OPENBLAS_NUM_THREADS"] = NUM_THREADS

import torch
torch.set_num_threads(int(NUM_THREADS))

from kafka import KafkaConsumer, KafkaProducer
from doclayout_yolo import YOLO

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Sửa dấu \ thành / để chạy được trên Linux (Docker)
MODEL_PATH = os.getenv(
    "MODEL_PATH",
    "models/doclayout_yolo_docstructbench_imgsz1024.pt"
)

logging.info("Loading layout model...")
model = YOLO(MODEL_PATH)

# --- KHU VỰC VÁ LỖI CHO MÔ HÌNH CUSTOM (MONKEYPATCH) ---
# 1. Vá lỗi '.bn' (Giao tranh giữa Ultralytics Fusion và BatchNorm)
model.model.fuse = lambda *args, **kwargs: model.model

# 2. Vá lỗi 'dict object has no attribute shape' (Bóc tách Tensor từ Dict đầu ra)
original_forward = model.model.forward

def patched_forward(*args, **kwargs):
    result = original_forward(*args, **kwargs)
    # Nếu kết quả trả về là dict và chứa key chuyên dụng cho YOLOv10/DocLayout
    if isinstance(result, dict) and 'one2one' in result:
        return result['one2one']
    if isinstance(result, dict):
        return result.get('preds', list(result.values())[0])
    return result

model.model.forward = patched_forward
# --------------------------------------------------------

logging.info("Layout model loaded")

# Nhãn gốc của DocLayout-YOLO (docstructbench) -> loại vùng của pipeline.
# None = bỏ qua (header/footer...). Công thức được cắt ảnh như figure.
NAME_MAP = {
    "title": "title",
    "plain text": "text",
    "abandon": None,
    "figure": "figure",
    "figure_caption": "text",
    "table": "table",
    "table_caption": "text",
    "table_footnote": "text",
    "isolate_formula": "figure",
    "formula_caption": "text",
}

# =====================================================
# MINIO & KAFKA
# =====================================================
s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
    aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "admin"),
    aws_secret_access_key=os.environ["MINIO_SECRET_KEY"]
)

broker = os.getenv("KAFKA_BROKER", "kafka:9092")

consumer = KafkaConsumer(
    "image-arrived",
    bootstrap_servers=[broker],
    group_id="layout-detector-group",
    auto_offset_reset="latest",
    # Commit thủ công sau khi đã gửi layout-completed: sập giữa chừng thì trang được xử lý lại
    enable_auto_commit=False,
    value_deserializer=lambda x: json.loads(x.decode("utf-8"))
)

producer = KafkaProducer(
    bootstrap_servers=[broker],
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    linger_ms=5
)

def detect_layout(img):
    # Đảm bảo ép chạy hoàn toàn trên CPU
    results = model.predict(img, conf=0.25, device="cpu", verbose=False)
    regions = []
    boxes = results[0].boxes

    for idx in range(len(boxes)):
        cls = int(boxes.cls[idx])
        rtype = NAME_MAP.get(model.names.get(cls, ""))
        if rtype is None:
            continue
        x1, y1, x2, y2 = map(int, boxes.xyxy[idx])

        regions.append({
            "id": idx,
            "type": rtype,
            "bbox": [x1, y1, x2, y2]
        })
    return regions

# =====================================================
# MAIN LOOP
# =====================================================
logging.info("Listening image-arrived...")

for message in consumer:
    try:
        data = message.value
        bucket = data.get("bucket", "data-lake")
        image_path = data.get("image_path")

        if not image_path:
            continue

        logging.info(f"Processing {image_path}")

        # LOAD IMAGE
        obj = s3.get_object(Bucket=bucket, Key=image_path)
        img = cv2.imdecode(
            np.frombuffer(obj["Body"].read(), np.uint8),
            cv2.IMREAD_COLOR
        )

        if img is None:
            logging.error(f"Cannot decode {image_path}")
            continue

        # DETECT
        regions = detect_layout(img)
        logging.info(f"Detected {len(regions)} regions")

        # BUILD MESSAGE
        # Key ảnh: pic/<path_chuan>/<ten_pdf>/page_N.png -> document_id = tên thư mục chứa trang
        document_id = os.path.basename(os.path.dirname(image_path)) or "unknown"
        page = os.path.splitext(os.path.basename(image_path))[0]

        try:
            total_pages = int(data.get("total_pages"))
        except (TypeError, ValueError):
            total_pages = None

        output = {
            "document_id": document_id,
            "total_pages": total_pages,
            "page": page,
            "bucket": bucket,
            "original_image": image_path,
            "regions": regions,
            "created_at": time.time()
        }

        # SEND
        producer.send("layout-completed", value=output)
        producer.flush()
        logging.info("Published layout-completed")

    except Exception as e:
        logging.exception(f"ERROR: {e}")
    finally:
        consumer.commit()