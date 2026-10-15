# AGENT_HANDOFF — Bàn giao trạng thái đồ án OCR

> **Đọc file này trước** khi agent / người mới tiếp tục dự án.  
> Hướng dẫn chạy thường ngày nằm ở `README.txt`.  
> **Cập nhật lần cuối:** 2026-10-08 chiều (OCR chữ trong bảng → bảng Markdown, TC01–TC11 đạt, báo cáo + slide đã cập nhật số liệu thật).  
> **Workspace:** `d:\Đồ án công nghệ phần mềm\Thesis`

---

## 1. Dự án là gì?

Hệ thống **OCR tiếng Việt** dạng microservices:

1. Preprocess PDF → ảnh trang  
2. Layout (DocLayout-YOLO)  
3. Crop dòng (PaddleOCR)  
4. Nhận dạng (VietOCR fine-tune)  
5. Reconstruct từng trang + Merge cả tài liệu  

Orchestration: **NiFi + Kafka + MinIO**.

Phần **train model** tách ở `d:\Đồ án công nghệ phần mềm\hieu_vietocr\` (dataset nặng).  
Phần **chạy thật** nằm trong `Thesis/OCR_pipeline/`.

---

## 2. Tiến độ (đã làm tới đâu)

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| Sắp xếp cấu trúc `Thesis/` | ✅ Xong | docs, training_vietocr, OCR_pipeline |
| Đặt model YOLO + VietOCR đúng chỗ | ✅ Xong | xem mục 4 |
| Viết lại service `merge/` (trước thiếu) | ✅ Xong | Kafka `document-completed` → MinIO `final/` |
| Sửa VietOCR dùng `transformerocr_final.pth` | ✅ Xong | trước đó sai `vgg_seq2seq` |
| Docker build + `compose up` cả stack | ✅ Xong (2026-09-20) | fix MinIO/PyTorch/OpenCV |
| Import + cấu hình NiFi template | ✅ Xong (REST API) | 9 processor RUNNING + VALID |
| Sửa 4 lỗi logic pipeline (xem mục 7b) | ✅ Xong (2026-10-02) | class layout, document_id, total_pages, trang rỗng |
| Web UI upload/xem kết quả | ✅ Xong | `OCR_pipeline/web_ui/`, http://localhost:8501 |
| MinIO → Docker volume `ocr_minio_data` | ✅ Xong (2026-10-03) | bind mount Windows gây lỗi I/O, mất dữ liệu |
| **E2E test** (upload PDF → có output) | ✅ Pass (2026-10-03) | PDF 3 trang ~2m45s, đủ box, merge `complete`, không timeout |
| UI demo / hoàn thiện báo cáo | ❓ Ngoài setup kỹ thuật | File trong `docs/` |

**Một câu:** Pipeline chạy thông end-to-end qua Web UI. Việc tiếp theo là nâng chất lượng (box trùng lặp, độ chính xác dấu tiếng Việt).

---

## 3. Cấu trúc quan trọng

```
Thesis/
  README.txt              ← hướng dẫn cài / chạy
  AGENT_HANDOFF.md        ← file này (tiến độ + ngữ cảnh)
  docs/                   ← báo cáo, đề cương
  training_vietocr/       ← script train (tham khảo)
  OCR_pipeline/           ← runtime Docker
    docker-compose.yml
    template_nifi.xml
    Preprocess_service/
    layout_detector/
    paddleocr_crop/
    vietocr_api/
    ocr_reconstruction/
    merge/
```

Ngoài Thesis (cùng thư mục cha):

- `hieu_vietocr/` — train + dataset + weights gốc  
- `template_nifi.xml`, `Thesis.pdf`, đề cương `.docx` — bản gốc  

---

## 4. Model

| File | Path | Có chưa |
|---|---|---|
| `doclayout_yolo_docstructbench_imgsz1024.pt` | `OCR_pipeline/layout_detector/models/` | ✅ |
| `transformerocr_final.pth` | `OCR_pipeline/vietocr_api/weights/` | ✅ |
| `vgg_seq2seq.pth` | — | ❌ Không dùng |

Drive backup: https://drive.google.com/drive/folders/1vYJTxqaUrATSfzEKu-F5X9HfaZnDH_jW

---

## 5. Luồng & Kafka topics

```
raw/*.pdf → NiFi → preprocess:5000
  → Kafka image-arrived → layout
  → layout-completed → paddle crop
  → crop-completed → vietocr
  → ocr-completed → reconstruct  (text/, preprocessed/)
  → document-completed → merge   (final/<document_id>/)
```

Topics: `image-arrived`, `layout-completed`, `crop-completed`, `ocr-completed`, `document-completed`, `merge-completed`.

---

## 6. Credentials & ports

| Service | URL | Login |
|---|---|---|
| NiFi | https://localhost:8443/nifi/ | `NIFI_USERNAME` / `NIFI_PASSWORD` |
| MinIO Console | http://localhost:9001 | `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` |
| MinIO S3 | http://localhost:9000 | `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` |
| **Web UI** | http://localhost:8501 | không cần login (cổng 8080 bị CVAT/traefik chiếm) |
| Preprocess | http://localhost:5000 | POST `/process` |
| Kafka | localhost:9092 | — |

Mật khẩu thật nằm trong `OCR_pipeline/.env` (không đưa lên git; mẫu: `.env.example`). Code Python không còn mật khẩu mặc định, thiếu biến `MINIO_SECRET_KEY` thì worker báo lỗi ngay.

NiFi S3 đã set: Endpoint `http://minio:9000`, bucket `data-lake`, ListS3 prefix `raw/`, key/secret theo `.env`.

---

## 7. Fix kỹ thuật đã áp dụng (tránh làm lại)

- `minio/minio` Docker Hub lỗi → `quay.io/minio/minio:latest` trong compose  
- PyTorch: dùng `--extra-index-url` (không chỉ `--index-url`)  
- Ghim `opencv-python-headless==4.8.1.78` (tránh lỗi hash)  
- Bỏ attribute `version` obsolete trong compose  

Docker Desktop path thường gặp:  
`C:\Users\Admin\AppData\Local\Programs\DockerDesktop\Docker Desktop.exe`

---

## 7b. Lỗi đã sửa ở session 2026-10-02/03 (đừng làm lại)

- **Layout** `CLASS_MAP` sai so với model docstructbench (`model.names`: title, plain text, abandon, figure, ...). Nay map theo tên (`NAME_MAP`), bỏ `abandon`, công thức → figure.
- **`document_id` luôn là `raw`** (NiFi `path_chuan` = `raw`). Nay lấy từ tên thư mục chứa trang: `basename(dirname(image_path))`.
- **`total_pages` bị mất** giữa chuỗi. Nay truyền layout → crop → vietocr → reconstruct → merge. Merge xong ngay khi đủ trang (`complete`).
- **Trang rỗng** làm kẹt merge: crop gửi marker `content_type="empty"`, `total_boxes=0` xuống `ocr-completed`.
- Crop hỏng làm lệch `total_boxes`: cắt ảnh trước rồi mới đếm.
- **Merge**: timeout tính theo thời gian rảnh, trang đến muộn thì merge lại thay vì ghi đè, sắp trang theo số tự nhiên.
- **VietOCR**: retry đọc S3 3 lần; crop không đọc được vẫn gửi text rỗng (không bỏ box).
- InvokeHTTP Read Timeout 15s → 5 mins (đã đổi cả template lẫn NiFi đang chạy qua REST API).
- Paddle: model lưu ở `OCR_pipeline/data/paddleocr_models` (volume), `logging.basicConfig(force=True)`.
- **MinIO**: bind mount `./data/minio` trên ổ Windows gây `input/output error`, file `part.1` 0 byte → 503 `SlowDownRead`. Đã chuyển sang volume `ocr_minio_data`; thư mục `data/minio` cũ giữ làm bản sao lưu (có thể xóa).

## 7b2. Sửa ngày 2026-10-08

- **Box trùng** (dòng bị lặp): vùng layout chồng nhau làm Paddle phát hiện 1 dòng 2 lần → `dedup_boxes()` trong `crop_paddleocr.py` (giao > 50% box nhỏ → giữ box lớn).
- **Trang có bảng bị mất chữ**: ô bảng đi tắt tới reconstruct sớm, các dòng chữ xếp hàng lâu ở VietOCR → hết timeout (tính từ box đầu) → ghi trang thiếu. Nay reconstruct tính timeout theo thời gian rảnh, giữ buffer để ghép lại khi box đến muộn; merge đọc lại toàn bộ trang trên MinIO mỗi lần ghép (`fill_from_storage`) và ghi `status` (`success`/`partial`) vào `final/<id>/<id>.json`. Web UI hiện "Hoàn tất một phần" khi `partial`.
- Volume `ocr_minio_data` khai báo `external: true` trong compose.

## 7b3. Kết quả đo (tools/eval_ocr.py, 2026-10-08)

Tài liệu: đề cương ĐATN (Word → PDF, 4 trang), đáp án = `pdftotext`. Kết quả: `OCR_pipeline/tools/results/eval_decuong_2026-10-08.json`.

| Chỉ số | Giá trị |
|---|---|
| Văn bản thường (trang 2) | CER 2.92%, WER 11.28%, F1 từ 89.81% |
| Toàn tài liệu | CER 34.81%, WER 40.28%, P/R/F1 từ 90.98% / 61.70% / 73.53% |
| Thời gian | 184.7 s / 4 trang (46.2 s/trang), CPU, CVAT tắt |
| RAM tối đa | NiFi ~1.35 GB, Paddle ~0.9 GB, Kafka ~0.76 GB, Layout ~0.66 GB, VietOCR ~0.5 GB |

Recall thấp ở trang 3–4 do **bảng chỉ cắt thành ảnh, chưa OCR chữ trong bảng** (precision vẫn 94–100%). CER bị phóng đại thêm vì thứ tự đọc bảng khác `pdftotext`.

## 7b4. Bảng Markdown + kiểm thử đầy đủ (2026-10-08 chiều)

- **Bảng**: crop vẫn lưu ảnh bảng vào `assets/` (+ thẻ `[TABLE: …]`) và còn OCR chữ trong bảng (`content_type=table_cell`, `table_id`). Reconstruct dựng bảng Markdown: cột = cụm `x_min` xuất hiện ≥ 2 hàng; hàng trống cột đầu = dòng tiếp của ô nhiều dòng. Merge xuất thêm `final/<id>/<id>.md`.
- Reconstruct: chiều cao dòng TB chỉ tính box chữ (trước đây ô giả ảnh/bảng làm gom dòng sai).
- Web UI: `#doc=<id>` mở thẳng tài liệu; route bắt cuối `/api/documents/{path}` trả 400 cho id chứa `/` hoặc `..` (TC10).
- **vietocr build**: build cache mất + mạng chậm làm tải PyTorch lỗi. Khi chỉ đổi `app.py`, vá nhanh: `FROM vietocr-worker-cpu` + `COPY app.py .` rồi tag lại `vietocr-worker-cpu`.
- Kết quả đo (tools/results/): đề cương 4 trang có bảng **CER 5,44%, F1 từ 88,21%**, 54,9 s/trang; mẫu ĐATN 10 trang F1 77,7%, **36,1 s/trang** (đáp án có header/footer + chấm dẫn mục lục). TC01–TC11 đạt: `tools/results/kiem_thu_2026-10-08.md`.
- Báo cáo `..\BaoCao_DATN_NguyenDinhDo.docx` (+ .pdf) và slide `..\Slide_DATN_NguyenDinhDo.pptx` đã cập nhật; bản 06/10 giữ lại với hậu tố "(ban 06-10)". Còn để sinh viên điền: 3 ảnh chụp (docker compose ps, canvas NiFi, MinIO Console) và số "ĐỢT ……" ở tiêu đề trang.
- Tài liệu cũ `Slide_MathModelling` trên UI kẹt "Đang nhận dạng 27/27" là dữ liệu chạy trước khi sửa lỗi (kết quả từng ghi vào `final/raw/`), không phải lỗi mới.

## 7c. Lưu ý vận hành

- Docker Desktop dùng chung ~8 GB RAM với CVAT/nuclio. Khi quá tải engine có thể treo (`docker stop` không phản hồi); cách gỡ: restart máy, rồi dừng CVAT trước khi chạy OCR nặng.
- NiFi không tạo lại container (flow nằm trong volume ẩn danh); dùng `docker compose up -d --no-deps <service>` để tránh đụng NiFi.
- Kafka dùng `auto_offset_reset=latest`: chỉ upload PDF sau khi `layout`, `paddleocr`, `vietocr` đã sẵn sàng.

## 8. File code đã sửa / thêm trong session setup

- `OCR_pipeline/docker-compose.yml`  
- `OCR_pipeline/vietocr_api/app.py`, `dockerfile`, `requirements.txt`  
- `OCR_pipeline/layout_detector/dockerfile`  
- `OCR_pipeline/paddleocr_crop/requirements.txt`  
- `OCR_pipeline/merge/` (mới: `app.py`, `dockerfile`, `requirements.txt`)  

---

## 9. Việc nên làm tiếp

0. **Việc nên làm tiếp:** (a) cải thiện dấu tiếng Việt (fine-tune VietOCR / hậu xử lý ngôn ngữ); (b) bộ tài liệu quét có đáp án để đo; (c) sinh viên chụp 3 ảnh còn thiếu trong báo cáo  
1. Bật Docker → `cd OCR_pipeline` → `docker compose up -d` → `docker compose ps`  
2. Upload PDF qua Web UI http://localhost:8501 (hoặc MinIO `data-lake/raw/`)  
3. Theo dõi log: `layout-worker`, `paddleocr-worker`, `vietocr-worker`, `reconstruct-worker`, `merge-worker`  
4. Kiểm tra output: `text/`, `preprocessed/`, `final/`  
5. Nếu ListS3 không nhặt file cũ: upload tên file mới hoặc clear state ListS3 trên NiFi  
6. Nếu NiFi container tạo mới mất flow: import lại `template_nifi.xml` + set credentials  

---

## 10. Quy ước cho agent tiếp

- Trả lời user bằng **tiếng Việt**  
- Không `git commit` trừ khi user yêu cầu  
- Ưu tiên E2E / bug runtime trước refactor lớn  
- Khi tiến độ đổi (E2E pass, đổi kiến trúc…): **cập nhật mục 2 + ngày đầu file này**

---

*Hướng dẫn chạy chi tiết: `README.txt`*
