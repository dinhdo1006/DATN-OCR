import os
import cv2
import numpy as np
import boto3
import json
import time
import logging

# =====================================================
# GIỚI HẠN CPU KHẮT KHE (Tránh treo Docker Desktop)
# =====================================================
NUM_THREADS = "2"
os.environ["CPU_NUM_THREADS"] = NUM_THREADS
os.environ["OMP_NUM_THREADS"] = NUM_THREADS
os.environ["MKL_NUM_THREADS"] = NUM_THREADS
os.environ["OPENBLAS_NUM_THREADS"] = NUM_THREADS

from paddleocr import PaddleOCR
from kafka import KafkaConsumer, KafkaProducer

logging.basicConfig(level=logging.INFO, force=True, format="%(asctime)s - %(levelname)s - %(message)s")

# =========================
# UTILS
# =========================
def normalize_box(box):
    if hasattr(box, "tolist"):
        box = box.tolist()
    if isinstance(box, list) and len(box) == 8:
        box = [
            [box[0], box[1]],
            [box[2], box[3]],
            [box[4], box[5]],
            [box[6], box[7]],
        ]
    return box

def _bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def dedup_boxes(boxes, overlap_thresh=0.5):
    """Bỏ box trùng: các vùng layout chồng nhau khiến một dòng bị phát hiện 2 lần.

    Hai box bị coi là trùng khi phần giao chiếm > overlap_thresh diện tích box nhỏ hơn.
    Giữ box lớn hơn (bao đủ chữ hơn).
    """
    def area(b):
        x1, y1, x2, y2 = b
        return max(0, x2 - x1) * max(0, y2 - y1)

    ordered = sorted(boxes, key=lambda b: area(_bbox(b["coordinates"])), reverse=True)
    kept = []
    for b in ordered:
        bb = _bbox(b["coordinates"])
        dup = False
        for k in kept:
            kb = _bbox(k["coordinates"])
            ix = max(0, min(bb[2], kb[2]) - max(bb[0], kb[0]))
            iy = max(0, min(bb[3], kb[3]) - max(bb[1], kb[1]))
            smaller = min(area(bb), area(kb))
            if smaller > 0 and ix * iy / smaller > overlap_thresh:
                dup = True
                # Dòng nằm trong bảng: giữ nhãn ô bảng để reconstruct dựng đúng hàng của bảng
                if b.get("content_type") == "table_cell" and k.get("content_type") != "table_cell":
                    k["content_type"] = "table_cell"
                    k["table_id"] = b.get("table_id")
                break
        if not dup:
            kept.append(b)
    return kept


def get_rotate_crop_image(img, points, padding=2):
    points = np.array(points).astype(np.float32)
    w = int(max(np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[2] - points[3])))
    h = int(max(np.linalg.norm(points[0] - points[3]), np.linalg.norm(points[1] - points[2])))

    if w <= 0 or h <= 0:
        return None

    pts_std = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    M = cv2.getPerspectiveTransform(points, pts_std)
    dst = cv2.warpPerspective(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC)

    if padding > 0:
        dst = cv2.copyMakeBorder(dst, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=[255, 255, 255])
    return dst

# =========================
# MAIN
# =========================
def main():
    s3 = boto3.client(
        's3',
        endpoint_url=os.getenv('MINIO_ENDPOINT', 'http://minio:9000'),
        aws_access_key_id=os.getenv('MINIO_ACCESS_KEY', 'admin'),
        aws_secret_access_key=os.environ['MINIO_SECRET_KEY']
    )

    logging.info("Loading PaddleOCR...")
    ocr = PaddleOCR(lang='vi', rec=False, use_angle_cls=False, show_log=False)
    logging.info("PaddleOCR loaded")

    broker = os.getenv('KAFKA_BROKER', 'kafka:9092')
    consumer = KafkaConsumer(
        'layout-completed',
        bootstrap_servers=[broker],
        group_id='ocr-crop-group',
        auto_offset_reset='latest',
        # Commit thủ công sau khi đã gửi hết box của trang: sập giữa chừng thì trang được xử lý lại
        enable_auto_commit=False,
        max_poll_records=10
    )
    producer = KafkaProducer(
        bootstrap_servers=[broker],
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        linger_ms=5
    )

    logging.info("Listening layout-completed...")

    for message in consumer:
        try:
            data = json.loads(message.value.decode('utf-8'))
            bucket = data.get('bucket', 'data-lake')
            image_path = data.get('original_image')
            regions = data.get('regions', [])

            if not image_path:
                continue

            logging.info(f"Processing {image_path}")

            obj = s3.get_object(Bucket=bucket, Key=image_path)
            img = cv2.imdecode(np.frombuffer(obj['Body'].read(), np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue

            # ĐỊNH NGHĨA PATH TRƯỚC ĐỂ XỬ LÝ S3
            sub_path = os.path.dirname(image_path).replace("pic/", "", 1)
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            
            text_boxes = []
            non_text_elements = []

            # Phân loại rẽ nhánh vùng dữ liệu từ YOLO
            for ridx, region in enumerate(regions):
                rtype = region.get("type", "text")
                x1, y1, x2, y2 = region["bbox"]
                region_img = img[y1:y2, x1:x2]

                if region_img.size == 0:
                    continue

                # Nhóm chữ (text, title, list) -> Chạy qua trích xuất dòng của Paddle
                if rtype in ["text", "title", "list"]:
                    dt_boxes, _ = ocr.text_detector(region_img)
                    if dt_boxes is None or len(dt_boxes) == 0:
                        continue

                    for box in dt_boxes:
                        box = normalize_box(box)
                        if not box or len(box) != 4:
                            continue

                        # Đẩy tọa độ về ảnh gốc toàn trang
                        shifted = [[int(p[0] + x1), int(p[1] + y1)] for p in box]
                        text_boxes.append({
                            "coordinates": shifted,
                            "content_type": rtype,
                            "region_id": ridx,
                            "region_bbox": [x1, y1, x2, y2],
                        })

                # Nhóm phi ngôn ngữ (figure, table) -> Cắt khối lưu S3 làm asset.
                # Bảng còn được OCR chữ bên trong (table_cell) để reconstruct dựng bảng Markdown.
                elif rtype in ["figure", "table"]:
                    success, buffer = cv2.imencode('.png', region_img)
                    if not success:
                        continue

                    asset_key = f"assets/{sub_path}/{base_name}_{rtype}_{ridx}.png"
                    s3.put_object(Bucket=bucket, Key=asset_key, Body=buffer.tobytes())

                    if rtype == "table":
                        dt_boxes, _ = ocr.text_detector(region_img)
                        for box in (dt_boxes if dt_boxes is not None else []):
                            box = normalize_box(box)
                            if not box or len(box) != 4:
                                continue
                            shifted = [[int(p[0] + x1), int(p[1] + y1)] for p in box]
                            text_boxes.append({
                                "coordinates": shifted,
                                "content_type": "table_cell",
                                "table_id": asset_key,
                                "region_id": ridx,
                                "region_bbox": [x1, y1, x2, y2],
                            })

                    # Tạo khung tọa độ giả lập cho khối
                    fake_box = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
                    non_text_elements.append({
                        "coordinates": fake_box,
                        "content_type": rtype,
                        "recognized_text": f"[{rtype.upper()}: {asset_key}]",
                        "s3_key": asset_key,
                        "region_id": ridx,
                        "region_bbox": [x1, y1, x2, y2],
                    })

            removed = len(text_boxes)
            text_boxes = dedup_boxes(text_boxes)
            removed -= len(text_boxes)
            if removed:
                logging.info(f"{base_name}: bỏ {removed} box trùng")

            # Cắt ảnh trước, bỏ box hỏng để total_boxes luôn khớp số message thực gửi đi
            valid_boxes = []
            for b in text_boxes:
                cropped = get_rotate_crop_image(img, b["coordinates"], padding=2)
                if cropped is None:
                    continue
                success, buffer = cv2.imencode('.png', cropped)
                if not success:
                    continue
                b["png"] = buffer.tobytes()
                valid_boxes.append(b)
            text_boxes = valid_boxes

            # TÍNH TỔNG SỐ HỘP THỰC TẾ TRÊN TRANG GIẤY
            total_boxes = len(text_boxes) + len(non_text_elements)
            if total_boxes == 0:
                # Trang rỗng: vẫn báo xuống reconstruct để merge không bị kẹt chờ trang này
                producer.send("ocr-completed", value={
                    "document_id": data.get("document_id") or os.path.basename(os.path.dirname(image_path)) or "unknown",
                    "total_pages": data.get("total_pages"),
                    "page": base_name,
                    "original_image": image_path,
                    "bucket": bucket,
                    "box_id": 0,
                    "total_boxes": 0,
                    "coordinates": None,
                    "content_type": "empty",
                    "recognized_text": "",
                    "created_at": time.time()
                })
                producer.flush()
                logging.info(f"Page {base_name} has no content, sent empty marker.")
                continue

            document_id = data.get("document_id") or os.path.basename(os.path.dirname(image_path)) or "unknown"
            total_pages = data.get("total_pages")

            # 1. Gửi các hộp CHỮ lên topic 'crop-completed' để VietOCR nhận diện
            output_dir = f"crop/{sub_path}"
            for idx, b in enumerate(text_boxes):
                s3_key = f"{output_dir}/{base_name}_crop_{idx}.png"
                s3.put_object(Bucket=bucket, Key=s3_key, Body=b["png"])

                msg = {
                    "document_id": document_id,
                    "total_pages": total_pages,
                    "page": base_name,
                    "original_image": image_path,
                    "bucket": bucket,
                    "s3_key": s3_key,
                    "box_id": idx,  # ID từ 0 đến len(text_boxes)-1
                    "total_boxes": total_boxes,
                    "coordinates": b["coordinates"],
                    "content_type": b["content_type"],
                    "table_id": b.get("table_id"),
                    "region_id": b.get("region_id"),
                    "region_bbox": b.get("region_bbox"),
                    "created_at": time.time()
                }
                producer.send("crop-completed", value=msg)

            # 2. GỬI THẲNG các hộp ẢNH/BẢNG lên thẳng 'ocr-completed' (Đi tắt đón đầu)
            for idx, env in enumerate(non_text_elements):
                global_idx = len(text_boxes) + idx  # Đảm bảo ID không bị trùng với hộp chữ
                
                msg_non_text = {
                    "document_id": document_id,
                    "total_pages": total_pages,
                    "page": base_name,
                    "original_image": image_path,
                    "bucket": bucket,
                    "s3_key": env["s3_key"],
                    "box_id": global_idx,
                    "total_boxes": total_boxes,
                    "coordinates": env["coordinates"],
                    "content_type": env["content_type"],
                    "recognized_text": env["recognized_text"],  # Thẻ định danh [FIGURE:...]
                    "region_id": env["region_id"],
                    "region_bbox": env["region_bbox"],
                    "created_at": time.time()
                }
                producer.send("ocr-completed", value=msg_non_text)

            producer.flush()
            logging.info(f"Published page {base_name}: {len(text_boxes)} text crops, {len(non_text_elements)} assets.")

        except Exception as e:
            logging.error(f"Error processing message: {e}")
        finally:
            consumer.commit()

if __name__ == "__main__":
    main()