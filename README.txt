# ĐỒ ÁN: Hệ thống OCR tiếng Việt (pipeline microservices)

## Cấu trúc thư mục

```
Thesis/
  README.txt                 ← hướng dẫn chạy (file này)
  AGENT_HANDOFF.md           ← trạng thái dự án cho agent / người nối tiếp
  docs/                      ← báo cáo + đề cương
  training_vietocr/          ← script train/fine-tune VietOCR (tham khảo)
  OCR_pipeline/              ← hệ thống chạy thật (Docker)
    template_nifi.xml
    docker-compose.yml
    Preprocess_service/
    layout_detector/         ← model YOLO trong models/
    paddleocr_crop/
    vietocr_api/             ← weights/transformerocr_final.pth
    ocr_reconstruction/
    merge/
```

## Luồng xử lý

raw (MinIO) → NiFi → Preprocess → Kafka `image-arrived`
→ Layout (YOLO) → PaddleOCR crop → VietOCR → Reconstruct
→ Merge → `final/<document_id>/` trên MinIO

## Chuẩn bị trước khi chạy

### 1. Model Layout YOLO

File phải có tại:
  OCR_pipeline/layout_detector/models/doclayout_yolo_docstructbench_imgsz1024.pt

Backup Drive:
https://drive.google.com/drive/folders/1vYJTxqaUrATSfzEKu-F5X9HfaZnDH_jW?usp=drive_link

### 2. Model VietOCR

  OCR_pipeline/vietocr_api/weights/transformerocr_final.pth

### 3. Cài Docker Desktop

### 4. Tạo file mật khẩu `.env`

```powershell
cd OCR_pipeline
copy .env.example .env
```

Mở `OCR_pipeline/.env` và điền mật khẩu. File này không đưa lên git.

## Chạy hệ thống

```powershell
cd "d:\Đồ án công nghệ phần mềm\Thesis\OCR_pipeline"
docker compose up -d --build
```

## Cấu hình NiFi

1. Mở https://localhost:8443/nifi/
2. Đăng nhập: NIFI_USERNAME / NIFI_PASSWORD trong `.env`
3. Upload template: `OCR_pipeline/template_nifi.xml`
4. Kéo template vào canvas, Start toàn bộ flow
5. Với ListS3 / FetchS3Object / PutS3Object:
   - Access Key ID = MINIO_ACCESS_KEY trong `.env`
   - Secret Access Key = MINIO_SECRET_KEY trong `.env`
   - Endpoint MinIO = http://minio:9000 (trong mạng Docker)

> Lần setup 2026-09-20 đã import + cấu hình NiFi qua API. Nếu container NiFi tạo mới, làm lại bước trên.

## MinIO

- Console: http://localhost:9001
- Tài khoản: MINIO_ACCESS_KEY / MINIO_SECRET_KEY trong `.env`
- Bucket: data-lake
- Đẩy PDF/ảnh test vào prefix `raw/`

## Kết quả

- Từng trang: `text/...`, `preprocessed/...`
- Tài liệu đã merge: `final/<document_id>/`

## Ghi chú

- Chi tiết tiến độ / bàn giao agent: xem `AGENT_HANDOFF.md`
- Phần train VietOCR gốc: `..\hieu_vietocr\`
- Script train gọn: `training_vietocr/`
