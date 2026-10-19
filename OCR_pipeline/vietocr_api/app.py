import os
import json
import time
import io
import logging
import boto3
from botocore.config import Config
from PIL import Image
from kafka import KafkaConsumer, KafkaProducer
from kafka.structs import OffsetAndMetadata

# =====================================================
# GIỚI HẠN CPU KHẮT KHE (An toàn cho môi trường chạy nhiều Docker)
# =====================================================
# Chỉ cấp đúng 2 luồng để nhường tài nguyên cho các container khác
NUM_THREADS = "2"
os.environ["OMP_NUM_THREADS"] = NUM_THREADS
os.environ["MKL_NUM_THREADS"] = NUM_THREADS
os.environ["OPENBLAS_NUM_THREADS"] = NUM_THREADS

import torch
torch.set_num_threads(int(NUM_THREADS))

from vietocr.tool.predictor import Predictor
from vietocr.tool.config import Cfg

# =====================================================
# CONFIG
# =====================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Batch Size = 4 (Cân bằng: nhanh hơn xử lý từng ảnh nhưng không ngốn nhiều RAM)
BATCH_SIZE = 4 

# =====================================================
# INIT S3
# =====================================================
def init_s3():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "admin"),
        aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
        config=Config(connect_timeout=5, read_timeout=30)
    )

# =====================================================
# INIT OCR
# =====================================================
def init_vietocr():
    # Model chữ viết tay đã fine-tune (transformer), khớp config_handwriting_final.yml
    config_path = os.getenv("VIETOCR_CONFIG", "./config_handwriting_final.yml")
    weights_path = os.getenv("VIETOCR_WEIGHTS", "./weights/transformerocr_final.pth")

    if os.path.exists(config_path):
        config = Cfg.load_config_from_file(config_path)
    else:
        config = Cfg.load_config_from_name("vgg_transformer")

    config["weights"] = weights_path
    config["cnn"]["pretrained"] = False
    config["device"] = "cpu"
    config["predictor"]["beamsearch"] = False

    logging.info(f"Loading VietOCR weights: {weights_path}")
    return Predictor(config)

# =====================================================
# LOAD IMAGE
# =====================================================
def get_image(s3, bucket, key, retries=3):
    # Thử lại vài lần: MinIO đôi khi trả lỗi tạm thời (503) khi đọc/ghi chậm
    for attempt in range(1, retries + 1):
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            data = obj["Body"].read()

            if len(data) < 50:
                raise ValueError(f"object quá nhỏ ({len(data)} bytes)")

            return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:
            logging.error(f"S3 error {key} (lần {attempt}/{retries}): {e}")
            time.sleep(0.5 * attempt)
    return None

# =====================================================
# OCR
# =====================================================
def predict(detector, images):
    if not images:
        return []

    if len(images) == 1:
        return [detector.predict(images[0])]

    try:
        return detector.predict_batch(images)
    except Exception as e:
        logging.warning(f"Batch prediction failed, fallback to single: {e}")
        result = []
        for img in images:
            try:
                txt = detector.predict(img)
            except:
                txt = ""
            result.append(txt)
        return result

# =====================================================
# MAIN
# =====================================================
def main():
    s3 = init_s3()
    detector = init_vietocr()
    broker = os.getenv("KAFKA_BROKER", "kafka:9092")

    consumer = KafkaConsumer(
        "crop-completed",
        bootstrap_servers=[broker],
        group_id="vietocr-group",
        auto_offset_reset="latest",
        enable_auto_commit=False,
        max_poll_records=BATCH_SIZE,
        value_deserializer=lambda x: json.loads(x.decode())
    )

    producer = KafkaProducer(
        bootstrap_servers=[broker],
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode()
    )

    logging.info(f"VietOCR Worker started (Batch={BATCH_SIZE}, Threads={NUM_THREADS})")

    while True:
        packs = consumer.poll(timeout_ms=500, max_records=BATCH_SIZE)

        if not packs:
            continue

        start = time.time()
        images = []
        valid_idx = []  # vị trí trong records của những ảnh đọc được
        records = []
        commits = {}

        for tp, msgs in packs.items():
            for msg in msgs:
                data = msg.value
                img = get_image(s3, data.get("bucket"), data.get("s3_key"))

                # Luôn giữ record, kể cả khi không đọc được ảnh (text rỗng), để reconstruct
                # nhận đủ total_boxes thay vì chờ hết timeout
                records.append((msg, data))
                if img:
                    images.append(img)
                    valid_idx.append(len(records) - 1)

            commits[tp] = OffsetAndMetadata(msgs[-1].offset + 1, None)

        predicted = predict(detector, images)
        texts = [""] * len(records)
        for j, i in enumerate(valid_idx):
            texts[i] = predicted[j] if j < len(predicted) else ""

        for i, (msg, data) in enumerate(records):
            txt = texts[i]
            
            payload = {
                "document_id": data.get("document_id"),
                "total_pages": data.get("total_pages"),
                "page": data.get("page"),
                "box_id": data.get("box_id"),
                "original_image": data.get("original_image"),
                "total_boxes": data.get("total_boxes"),
                "coordinates": data.get("coordinates"),
                "content_type": data.get("content_type", "text"),
                "table_id": data.get("table_id"),
                "region_id": data.get("region_id"),
                "region_bbox": data.get("region_bbox"),
                "recognized_text": txt,
                "timestamp": time.time()
            }

            producer.send("ocr-completed", value=payload)

        producer.flush()

        if commits:
            consumer.commit(offsets=commits)

        logging.info(f"Processed {len(records)} records in {time.time()-start:.2f}s")

if __name__ == "__main__":
    main()