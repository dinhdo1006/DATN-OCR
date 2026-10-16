# AGENT_HANDOFF — Bàn giao trạng thái đồ án OCR

> **Đọc file này trước** khi agent / người mới tiếp tục dự án.  
> Hướng dẫn chạy thường ngày nằm ở `README.txt`.  
> **Cập nhật lần cuối:** 2026-10-16 trưa (báo cáo + slide hoàn thiện, bộ câu hỏi bảo vệ – mục 7b7; xử lý lỗi NiFi – 7b6; 15/10: dựng lại stack trên máy mới, so sánh trọng số VietOCR).  
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
| Git + tách mật khẩu ra `.env` | ✅ Xong (2026-10-15) | remote `github.com/dinhdo1006/DATN-OCR` (public); weights, `data/`, `.env` không commit |
| Dựng lại stack trên máy mới (i7-9750H) | ✅ Xong (2026-10-15) | E2E qua NiFi: đề cương CER 5,44%, F1 88,21%, 54,4 s/trang – khớp báo cáo |
| So sánh trọng số VietOCR | ✅ Xong (2026-10-15) | giữ `transformerocr_final.pth` (gốc `vgg_transformer` kém hơn); xem mục 7b5 |
| Xử lý lỗi NiFi (retry + `errors/` + UI "Lỗi") | ✅ Xong (2026-10-16) | template 11 processor; TC12, TC13 đạt; xem mục 7b6 |
| Báo cáo + slide hoàn thiện | ✅ Xong (2026-10-16) | xem mục 7b7; còn sinh viên điền "ĐỢT ……", kiểm tra TS/ThS của GVHD |
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
- `BaoCao_DATN_NguyenDinhDo.docx` / `.pdf` (bản mới nhất, 16/10), `Slide_DATN_NguyenDinhDo.pptx`, đề cương `.docx` (bản đúng lịch), mẫu trình bày ĐATN, `TaiLieu_TimHieu_DoAn`. Các bản sao lưu cũ và `template_nifi.xml` gốc đã xóa ngày 16/10 (bản đúng: `OCR_pipeline/template_nifi.xml`)  

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

- MinIO đã gỡ image khỏi Docker Hub và quay.io (10/2026: `denied` / 401) → dùng `pgsty/minio:RELEASE.2026-08-04T00-00-00Z` (bản build cộng đồng, giữ đủ Console). Máy mới: tạo volume `docker volume create ocr_minio_data` và bucket `data-lake` (`mc mb local/data-lake` trong container minio)  
- NiFi mới tạo: chạy `tools/setup_nifi.ps1` (upload template, điền khóa từ `.env`, prefix `raw/`, Start)  
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
- Báo cáo `..\BaoCao_DATN_NguyenDinhDo.docx` (+ .pdf) và slide `..\Slide_DATN_NguyenDinhDo.pptx` đã cập nhật. 3 ảnh chụp (Hình 3-1 docker compose ps, 3-2 canvas NiFi, 3-5 MinIO) đã chèn ngày 16/10 – bản gốc ở `OCR_pipeline/tools/results/anh_bao_cao/` (chụp bằng Chrome headless qua DevTools; MinIO bản pgsty hiển thị logo "SILO"). Còn để sinh viên điền: số "ĐỢT ……" ở tiêu đề trang.
- Tài liệu cũ `Slide_MathModelling` trên UI kẹt "Đang nhận dạng 27/27" là dữ liệu chạy trước khi sửa lỗi (kết quả từng ghi vào `final/raw/`), không phải lỗi mới.

## 7b5. Session 2026-10-15 (máy mới `C:\Users\hi`, Docker trống)

- **So sánh trọng số** (`tools/results/so_sanh_model_vietocr_2026-10-15.md`): `transformerocr_final.pth` tốt hơn `vgg_transformer` gốc trên cả hai tài liệu (đề cương CER 5,44% vs 11,18%; mẫu 10 trang 37,87% vs 38,80%). Gốc hay sinh từ thừa cuối dòng ("dựa trên thuật thức"). → Giữ nguyên. Báo cáo đã thêm Bảng 3-6.
- **Tái lập số đo**: dùng đúng tài liệu cũ (đề cương bản 4 trang = `docs/` cũ trong git `ce9c783`; mẫu ĐATN trang 9–18), đáp án `pdftotext` khớp từng ký tự với lần 08/10. Pipeline tất định: CER 5,44% trùng từng chữ số.
- `tools/setup_nifi.ps1`: upload template, điền khóa từ `.env` (template không chứa khóa bí mật), prefix `raw/`, Start. Lần đầu ListS3 liệt kê **mọi** PDF có sẵn trong `raw/` và xử lý lại. (Đính chính: template **có** lưu auto-terminate – nằm ở `<relationships><autoTerminate>`, không phải `config.autoTerminatedRelationships`; nhận định "template thiếu auto-terminate" trong commit `b2e4ccb` là sai.)
- **NiFi nuốt lỗi im lặng** (template cũ tự hủy mọi nhánh lỗi) → đã sửa ngày 16/10, xem 7b6.
- Thuộc tính thừa trong UpdateAttribute thứ 2 (`${invokehttp.response.header.X-…}`, luôn rỗng) và `path_chuan` luôn = `raw` – vô hại, worker/UI đã thích nghi.
- Build: PyTorch không ghim → bản 2.14.1, chạy tốt với vietocr 0.3.12. Mạng chậm/chập chờn: build từng image một, có retry.

## 7b6. Xử lý lỗi trong NiFi (2026-10-16)

Trước: PDF hỏng (qua được kiểm tra `%PDF` của Web UI) → preprocess trả 500 → nhánh Retry bị tự hủy → tài liệu kẹt "Đang chờ NiFi" mãi.

Nay (`template_nifi.xml` 11 processor / 15 connection, đã export lại từ NiFi):
- **Preprocess** trả **422** khi pdf2image không đọc được PDF (hỏng / có mật khẩu) hoặc PDF 0 trang → NiFi xếp vào `No Retry`, không thử lại vô ích.
- **Thử lại** (cơ chế retry của NiFi ≥ 1.16, lưu trong template): InvokeHTTP `Retry`+`Failure`, FetchS3Object / PutS3Object / PublishKafka `failure` – 3 lần, backoff phạt FlowFile (30 s → tối đa 2 phút).
- Hết lượt thử hoặc lỗi dữ liệu → **ReplaceText (bản ghi lỗi)** dựng JSON (`document_id`, `status_code`, `response` = body lỗi, `exception`, `failed_at`) → **PutS3Object (errors/)** ghi `errors/<ten_pdf>.json`.
- **Web UI**: có `errors/<id>.json` (và chưa có `final/`) → trạng thái `error`, nhãn "Lỗi" kèm lý do (lấy `detail` trong body lỗi).

Kiểm thử (`tools/results/kiem_thu_2026-10-16.md`): TC12 PDF hỏng → "Lỗi" sau ~3 s; TC13 tắt preprocess 40 s lúc tải lên → NiFi thử lại, tài liệu vẫn xong 4/4. Import template mới vào NiFi trắng → 11/11 VALID, giữ cấu hình retry.

Lưu ý: tạo NiFi mới thì ListS3 xử lý lại **mọi** PDF trong `raw/` (lần 16/10: 8 PDF ≈ 36 trang, ~25 phút). Trong lúc đó UI có thể hiện `partial` và merge ghép lặp lại – là trạng thái trung gian, tự về `done` khi hàng đợi hết. Kiểm tra hàng đợi: `docker exec kafka sh -c '/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --all-groups'` (cột LAG).

## 7b7. Báo cáo và slide (2026-10-16)

- **Tên đề tài giữ nguyên** (sinh viên không được đổi). Chỉ dùng `..\BaoCao_DATN_NguyenDinhDo.docx/.pdf` và `..\Slide_DATN_NguyenDinhDo.pptx`; bản "(ten moi)" đã bỏ vào Thùng rác.
- Báo cáo (77 trang): Bảng 3-6 so sánh trọng số; nhánh lỗi NiFi + lỗi (vii) + TC12–TC13; 3 ảnh chụp (Hình 3-1, 3-2, 3-5); mục "Đóng góp" thêm 3 gạch (bảng Markdown, nhánh lỗi NiFi, công cụ đánh giá + so sánh trọng số); trang bìa: "Hà Nội, 2026" đã về trang 1 (trang 2 để trắng, các trang sau giữ vị trí).
- Slide (24 slide): số liệu khớp báo cáo (11 lỗi logic, 13/13 ca, CER 5,44% vs 11,18%); thêm slide 17 "Xử lý lỗi trong luồng NiFi" (ảnh canvas) và slide 19 "So sánh trọng số VietOCR".
- Bộ câu hỏi bảo vệ (Claude Docs): https://claude.ai/code/artifact/35b91041-4db2-4c30-aaba-8880c621df6e
- Còn sinh viên tự làm: điền "ĐỢT ……" ở tiêu đề trang; thống nhất học hàm GVHD (báo cáo/slide ghi "TS.", đề cương ghi "ThS.").
- File mẫu `Mau trinh bay DATN CNPM - 21 07 2025.docx` không còn trong thư mục cha (không do agent xóa).

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
