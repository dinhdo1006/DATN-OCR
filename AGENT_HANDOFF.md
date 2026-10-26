# AGENT_HANDOFF — Bàn giao trạng thái đồ án OCR

> **Đọc file này trước** khi agent / người mới tiếp tục dự án.  
> Hướng dẫn chạy thường ngày nằm ở `README.txt`.  
> **Cập nhật lần cuối:** 2026-10-24 (vẽ lại hình cho dễ đọc khi in, sửa bảng 2-1, mục 2.7, thêm bảng bộ tài liệu kiểm thử – mục 7b11; 23/10: đối chứng, hiệu năng CPU/GPU – 7b10).
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
- **MinIO**: bind mount `./data/minio` trên ổ Windows gây `input/output error`, file `part.1` 0 byte → 503 `SlowDownRead`. Đã chuyển sang volume `ocr_minio_data`; thư mục `data/minio` cũ đã xóa ngày 22/10.

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

## 7b8. Sửa lỗi 19/10/2026 (thứ tự đọc nhiều cột, commit an toàn)

Chi tiết + số đo: `tools/results/kiem_thu_2026-10-19.md`.
- **Thứ tự đọc nhiều cột:** paddleocr gắn `region_id`/`region_bbox` vào box (vietocr chuyển tiếp); reconstruct `order_regions()` chia vùng thành dải theo y, dải có vùng hai phía đường giữa trang → cột trái rồi cột phải; gom dòng trên toàn bộ box của từng cột (YOLO có thể trả vùng chồng nhau). Box thiếu thông tin vùng → cách cũ. TC14 đạt.
- **Commit an toàn:** reconstruct chỉ commit tới offset nhỏ nhất của box thuộc trang chưa ghi MinIO, và `load_stored_boxes()` nạp lại trang đã ghi từ `preprocessed/…json` (JSON nay lưu thêm region). layout, paddleocr commit thủ công. TC15 (kill reconstruct giữa trang) đạt.
- **preprocess:** thư mục tạm riêng mỗi yêu cầu, xóa sau khi gửi ZIP.
- Đo lại: đề cương CER 4,95% (5,44% trước), F1 88,21% không đổi; mẫu 10 trang CER 38,10%, F1 77,51% không đổi. Báo cáo giữ số cũ làm mốc + thêm đoạn đo lại ở mục 3.10; lỗi (viii)–(x), TC14–TC15 (15 ca), mục Đóng góp, slide 5/13/18/22 đã cập nhật.
- Bộ câu hỏi bảo vệ (Claude Docs) **chưa cập nhật** bảng "Điểm yếu" cho 4 lỗi đã sửa (connector Docs mất kết nối 19/10).

## 7b9. Kiểm tra toàn hệ thống + sửa compose (21/10/2026)

Chi tiết: `tools/results/kiem_thu_2026-10-21.md`.
- **Kafka healthcheck**: 5 worker `depends_on: kafka: condition: service_healthy` → hết `NoBrokersAvailable` lúc bật. Khối `nifi` **không đổi** (đổi là container NiFi bị tạo lại, mất luồng).
- **Chờ Kafka trong worker** (22/10): `x-wait-kafka` (entrypoint chờ `KafkaAdminClient` kết nối được) – cần vì khi Docker tự bật lại container lúc khởi động máy thì healthcheck của compose không có tác dụng. Đã thử `docker desktop restart`: 0 lần khởi động lại.
- **Kafka bền vững**: image ghi vào `/tmp/kafka-logs` trong container (mount `./data/kafka` cũ không được dùng) → `KAFKA_LOG_DIRS=/var/lib/kafka/data` + volume `ocr_kafka_data`. Tạo lại container Kafka vẫn giữ offset.
- Chạy lại: 3 tài liệu đồng thời (web, trùng tên, `mc cp` vào `raw/`), PDF hỏng, TC02–TC04, TC10–TC11, kill VietOCR, `eval_ocr.py` (chạy trong container `ocr-web-ui`, `--api http://localhost:8080`) – tất cả đạt.
- Báo cáo mới nhất: `..\BaoCao_DATN_2221050598_NguyenDinhDo.docx/.pdf` (79 trang; GVHD **ThS.**; VietOCR do sinh viên tự fine-tune, dữ liệu 5CD-AI/VietHTR-Line = TLTK [27]). Slide: `..\Slide_DATN_2221050598_NguyenDinhDo.pptx`.

## 7b10. Theo nhận xét của GVHD: đối chứng, hiệu năng lặp lại, GPU, mở rộng (22–23/10/2026)

Chi tiết số liệu: `tools/results/kiem_thu_2026-10-22.md`, JSON đối chứng: `tools/results/doi_chung_2026-10-22/`.
- **Đối chứng** Tesseract 5.5 (vie, psm 3) và PaddleOCR 2.7 (vi/Latin) trên cùng ảnh trang + đáp án, cả bản quét mô phỏng (`tools/degrade_pdf.py`): `tools/baseline_ocr.py`, `tools/score_dir.py`. Kết luận trung thực: chữ thuần hệ thống ≈/kém Tesseract (F1 thấp hơn 0,6–8 điểm), hơn hẳn PaddleOCR (mất dấu); khác biệt chính là cấu trúc (bảng, thứ tự đọc).
- **GPU tùy chọn**: `docker-compose.gpu.yml` + `dockerfile.gpu` (PyTorch 2.7.1+**cu118** – driver 528.79 chỉ CUDA 12.0, bản cu126 lỗi trong WSL). `DEVICE` env trong layout/vietocr, VietOCR lô 16 trên GPU. Chạy: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build --no-deps layout_detector vietocr`; về CPU: `docker compose up -d --no-deps layout_detector vietocr`. Kết quả nhận dạng trùng CPU.
- **Đo lặp lại** `tools/bench.py` (chạy trong `ocr-web-ui`, `--api http://localhost:8080`, `--runs`, `--concurrent`): CPU (máy rảnh) 10 trang 125,0 ± 3,8 s, 42 trang 534,2 s; GPU 35,4 ± 4,6 s, 155,9 s, 120 trang 574,1 s. Đo CPU ban ngày bị nhiễu do người dùng chạy Chrome (~1–2 nhân) → không dùng làm số chính.
- **Lỗi OOM đã sửa**: `Preprocess_service/preprocess.py` nạp mọi trang 300 DPI vào RAM → GPU + 42 trang làm máy ảo Docker (7,67 GB) hết RAM, layout-worker bị kill (137). Đổi sang chuyển từng trang (`pdfinfo_from_path` + `first_page/last_page`), ảnh trùng md5, còn nhanh hơn.
- **Mở rộng ngang**: `docker-compose.scale.yml` (service `vietocr_2`). Topic `crop-completed` **hiện có 2 partition** (để lại, vô hại). 2 bản sao: 5 người nhanh 1,9×, 42 trang 1,6×.
- Công cụ thêm: `tools/fetch_pages.py` (tải text từng trang để chấm lại), `tools/clean_bench.py` (xóa dữ liệu `bench_*` khỏi MinIO).
- Web UI: chế độ Trình bày (render Markdown, ảnh bảng/hình qua `/api/assets`), tải `.md/.json/.txt` (`?fmt=`).
- Báo cáo 86 trang: mục 3.6 (4 hình mới, chữ to), 3.9 viết lại (Bảng 3-6 CPU/GPU, năng lực 120 trang / 5 người, OOM, mở rộng), 3.10 thêm Bảng 3-8/3-9 đối chứng, TC16–TC19 (19 ca), Bảng 3-4 thêm 2 lỗi, Phụ lục 4 thêm lệnh GPU/scale/bench. Slide 26 trang: thay hình slide 7/10/12/17/22, thêm slide 20 (đối chứng) và 21 (hiệu năng).

## 7b11. Rà soát hình, bảng trong báo cáo (24/10/2026)

- Vẽ lại 16 hình cho chữ in ra ≥ 7 pt (hình rộng 880 px, chèn 439 pt): 1-1, 1-3, 1-4, 1-5, 2-1, 2-2, 2-4, 2-5, 2-6, 2-7, 2-8, 2-12, 2-13, 2-14, 2-15, 2-16; cắt gọn 3-5. Mã nguồn hình: `docs/hinh_ve/` (dg.js, seq.js, README.txt). Biểu đồ tuần tự 2-9..2-11 giữ nguyên (7–8 pt).
- Sửa nội dung hình: 1-5 vẽ đúng topic crop-completed 2 partition + 2 bản sao vietocr; 2-7 PublishKafka xuất phát từ NiFi; 2-14 thêm `.md`, `errors/`; 2-16 có chế độ Trình bày/Văn bản và nút .md/.json/.txt.
- Sửa chữ: Bảng 2-1 (độ chính xác theo số đo thật), mục 2.7 (cả 5 worker commit thủ công), Bảng 3-3 (CPU/GPU, từng trang), rút gọn ô TC18/TC19; thêm Bảng 3-7 "Bộ tài liệu kiểm thử" (đề cương = đề cương ĐATN của sinh viên; độc lập với dữ liệu huấn luyện; hạn chế: 14 trang). Các bảng chương 3 sau đó tự đánh lại số (3-8 trọng số, 3-9 đối chứng, 3-10 trích đoạn, 3-11 mục tiêu).
- Lưu ý: worker PaddleOCR chạy `paddleocr_crop/crop_paddleocr.py` (group `ocr-crop-group`, commit thủ công); `paddleocr_crop/app.py` là bản cũ không dùng.
- Báo cáo 87 trang, slide 26 trang (slide 7, 10, 12, 17 dùng hình mới).

## 7b12. Chạy thử demo bảo vệ (24/10/2026)

- Thư mục `../Demo/` (ngoài repo): `demo_decuong_2trang.pdf` (trang 2–3 của decuong4.pdf, PDF xuất từ Word), `pdf_hong.pdf` (cắt cụt 20 KB), `HuongDan_Demo.txt` (chuẩn bị, kịch bản 4 bước, dự phòng), ảnh/Markdown dự phòng.
- CPU, 10 container, NiFi 11/11 Running: 2 trang xong sau 58 s và 59 s (lần 2 tên `bench_demo_2trang`, Markdown giống hệt trừ tên); `pdf_hong` báo lỗi HTTP 422 sau 2 s. Đã xóa dữ liệu `bench_*` bằng `tools/clean_bench.py --xoa`; giữ `demo_decuong_2trang` trong MinIO để làm kết quả có sẵn.
- Báo cáo: Tóm tắt, Bảng 3-11 (mục tiêu) và Kết luận đổi CER tài liệu có bảng từ 5,44% sang 4,95% cho khớp Bảng 3-9 (số đo sau cùng 19/10); Bảng 3-8 và các đoạn kể lần đo trước giữ 5,44%. Slide 18 đổi tương tự; slide 7, 19 (so sánh trọng số) giữ 5,44%. Báo cáo 85 trang.

## 7b13. Rà soát lại toàn bộ hình theo mã nguồn và quy tắc UML/DFD (25/10/2026)

- Hình 2-4 (DFD mức 0) vẽ lại cho cân bằng với Hình 2-1: thêm tiến trình 6.0 Tra cứu kết quả (trả trạng thái, kết quả cho Người dùng), tách tác nhân Hệ thống nguồn và Quản trị viên, thêm luồng 3.0 → 5.0 (hình, bảng, trang rỗng), thêm errors/ vào D1.
- Hình 2-5 (hoạt động): thêm nút quyết định "loại vùng?" có điều kiện [dòng chữ] / [hình, bảng, trang rỗng], nút hợp nhánh trước Gom box, nhánh [PDF hỏng] → errors/ → trạng thái Lỗi.
- Hình 2-6 (phân tầng): 4 tầng, Kafka và MinIO cùng ở tầng hạ tầng dưới cùng (trước đặt Kafka trên tầng AI worker, mâu thuẫn "phụ thuộc một chiều"); bỏ "Hệ thống nguồn" khỏi các tầng.
- Hình 2-16: ô tải lên nằm ngang phía trên như giao diện thật; Hình 1-2 vẽ lại (YOLO chạy cạnh dài 1024 theo imgsz của checkpoint, không phải 1024×1024); sửa nhãn đè ở 1-5, 2-15; 2-10 thêm trả về "ảnh dòng"; 3-1 không còn cắt dòng lệnh; 3-3 cắt bớt.
- Chữ báo cáo sửa theo hình (2.3.5, 2.3.6, 2.4.2, 2.10, kết chương 2); thêm đoạn giải thích Hình 2-10 sau Hình 2-9; khoảng cách trước dòng mục lục 3 → 2 pt (hết tràn 3 dòng sang trang iv). Báo cáo 83 trang; Word để trang 16 trắng nên MỞ ĐẦU vẫn ở trang 17 (trang lẻ) như trước, dù các ngắt mục đều là "trang mới" (chưa rõ cơ chế).
- Slide: 11 thay Hình 2-7 bản đã sửa (bản cũ vẽ PublishKafka từ preprocess), 12 thay Hình 2-4 mới và phóng to, 13 thay Hình 2-15 mới.

## 7b14. Rà tính nhất quán yêu cầu – ca sử dụng – đặc tả (25/10/2026)

- Hình 2-2 ghi mã UC01–UC09 (UC01 tải lên, UC02 xem danh sách và trạng thái xử lý, UC03 xem kết quả số hóa, UC04 tải xuống «extend» UC03, UC05–UC07 quản trị viên, UC08 hệ thống nguồn, UC09 hệ thống đích); slide 10 dùng hình mới.
- 2.3.4: đoạn mở đầu có truy vết FR → UC (FR01–UC01 … FR05–UC08, FR06–FR11 các bước Bảng 2-8, FR12–UC09) và lý do không đặc tả UC05–UC07. Tên UC02/UC03 trong chú thích và bảng khớp hình (dấu gạch là en dash U+2013). UC02, UC03 thêm dòng Mô tả, Tiền điều kiện; UC02 thêm luồng thay thế lỗi; Bảng 2-8 thêm 1a PDF hỏng, 1b lỗi tạm thời, hậu điều kiện đủ .md; NFR03 sửa "cả năm worker".
- Câu dẫn có số bảng cho Bảng 2-4, 2-9, 3-4, 3-5, 3-11. Bốn bảng đặc tả tắt SpaceBefore/AfterAuto (trước đó mỗi bước cách một dòng trống); các bảng khác giữ nguyên vì ô một đoạn không bị ảnh hưởng.
- Kiểm tra tham chiếu: 54 chú thích, không tham chiếu nào trỏ sai; mọi hình đều được nhắc trong văn bản. Bảng 2-10 (topic) và 2-12 (API) khớp mã nguồn. Báo cáo 83 trang.

## 7b15. Sửa theo phản biện độc lập (agent đọc toàn bộ báo cáo, 26/10/2026)

- Sai sự thật đã sửa: (1) 120 trang/CPU "25 phút" là ước tính (đo trực tiếp lúc máy bận 47 phút), ghi rõ ở Tóm tắt, Kết chương 3, Kết luận; (2) thí nghiệm 2 bản sao VietOCR: cấu hình 1 bản sao đo lúc 10:19 (821,9 s / 948,6 s) chậm hơn chính nó lúc 09:03 (420,9 s / 566,0 s) → mức tăng 1,6–1,9× KHÔNG dùng làm kết luận, chỉ khẳng định chạy được không sửa mã và chia đều 923/881 dòng (mục 3.9, Bảng 3-11, 3-12 NFR05 "đạt một phần", slide 21, tài liệu hỏi đáp, HuongDan_Demo); (3) final/<id>.json là CHỈ MỤC trang, JSON có tọa độ ở preprocessed/ (Hình 1-1, mục 3.10); (4) commit: layout/paddle commit trong finally (lỗi xử lý thì bỏ qua thông điệp), merge commit ngay khi nhận trang và nạp lại từ text/ (Bảng 1-3, NFR03, 2.5.2, 2.7); (5) bộ từ vựng 406 ký tự (không phải 402); (6) Bảng 2-11 int[4][2], thêm table_id/region_id/region_bbox, bỏ "list"; (7) "12 nguyên âm có dấu phụ…đ" → 6 nguyên âm mang dấu phụ, phụ âm đ.
- Bổ sung: TC20 (nạp qua S3, FR05) và TC21 (sự kiện merge-completed, FR12) chạy thật 26/10 → 21 ca (`tools/results/kiem_thu_2026-10-26.md`); Bảng 3-12 đối chiếu NFR01–07; Bảng 3-11 thêm mục tiêu UML; Phụ lục 4 thêm tạo .env, `docker volume create ocr_minio_data`, tải trọng số theo README.txt; đoạn mã 3.4.1 và doc_status theo mã hiện tại; câu dẫn có số cho các bảng; 10 từ viết tắt (49 mục).
- Hình vẽ lại theo ký pháp: 2-6 biểu đồ gói UML (tab, «use», gói "Worker xử lý"); 2-7 biểu đồ triển khai UML («device», «executionEnvironment», «container», artifact volume, đường truyền ghi giao thức); 2-4 DFD (3.0 đọc ảnh trang, 1.0 ghi bản ghi lỗi, 5.0 đọc văn bản từng trang, yêu cầu xem/tải vào 6.0, quản trị viên "cấu hình"/"nhật ký" hai chiều, kho D1 hở cạnh); 2-1 cân bằng tương ứng; 2-5 thêm "Trả lỗi 400/413", "Ghi errors/<id>.json"; 2-10 khung opt lồng trong loop, commit offset mọi worker (seq.js thêm `inset`, vẽ khung ngoài trước, `actors`); 2-11 Người dùng là tác nhân; 2-12 nhãn status.
- Tài liệu tham khảo đánh số lại theo IEEE (5CD-AI thành [17], [17]–[26] cũ thành [18]–[27]); 5 nguồn web thêm "[Truy cập: 26/10/2026]" (đã kiểm tra đường dẫn mở được).
- Chưa làm: đo lặp mở rộng 1↔2 bản sao (cần máy rảnh ~1,5 giờ); "CÁN BỘ PHẢN BIỆN: Tên thầy phản biện" ở bìa phụ và mã "ĐỢT" ở gáy chờ người dùng cung cấp. Báo cáo 85 trang.

## 7b16. Sửa theo bản nhận xét bên ngoài do người dùng dán vào (26/10/2026)

- Đã sửa: Tóm tắt và Kết luận nêu cả hai tài liệu (CER 4,95% / 38,10%, F1 88,2 / 77,5) kèm số đo trực tiếp 47 phút; Mở đầu ghi 5,44% → 4,95% sau khi thêm thứ tự đọc; câu về chữ đ; bỏ câu khẳng định "không tách được con dấu, chữ ký"; Bảng 1-4 ghi kế hoạch khác thực tế (kéo đến 26/10); câu về MinIO (lệnh pull trả 401/denied); "chưa chạy thử trên máy chủ Linux"; 87,30% trỏ tới `tools/results/doi_chung_2026-10-22`; 1.5.2 thêm đoạn chi tiết tinh chỉnh (406 ký tự, load_weights bỏ tham số lệch kích thước, OneCycleLR max_lr 3e-4, batch 16, 40k vòng, tăng cường dữ liệu, tập train 57.381 / val 5.552 dòng); Bảng 3-11 "Kiến trúc hướng sự kiện" = đạt một phần; Bảng 3-2 thêm cột Giấy phép (rộng 439 pt) và đoạn ghi chú AGPL/pgsty; Phụ lục 5 có lược đồ đủ sáu topic (merge-completed có thể phát nhiều lần, bên nhận phải idempotent), 2.7 trỏ tới Phụ lục 5; thêm FR, NFR, TC vào danh mục viết tắt; 50 chú thích dùng "-" (trước đó có ký tự 30). Báo cáo 88 trang.
- Ý kiến không đúng: công thức CIoU trong báo cáo tương đương (chỉ viết dạng khác); Bảng 2-1 "Cao" đã có ghi chú; ngôi "em" chỉ xuất hiện trong Lời cảm ơn.
- Chưa làm (cần người dùng quyết hoặc cần máy rảnh): đo cấu trúc bảng (TEDS hoặc độ chính xác ô) và thứ tự đọc; tính lại CER bỏ header/footer/dấu chấm dẫn; đo 120 trang CPU lúc máy rảnh; đo lặp mở rộng; ảnh quét thật; pytest + GitHub Actions; ma trận TC↔FR/NFR; chạy trên Linux; đổi auto_offset_reset=earliest; tách chương 3 và gộp phần Đóng góp; bổ sung nghiên cứu liên quan; nguồn nhãn và giấy phép dữ liệu công ty.
- Slide 24 (Kết luận) ghi F1 cho cả hai tài liệu, khớp báo cáo.
- Theo yêu cầu người dùng, tài liệu kiểm thử không còn gọi là "đề cương ĐATN" và "mẫu trình bày ĐATN". Hai tài liệu nay là **tài liệu A** (4 trang, 1.013 từ, 4.910 ký tự, văn bản kế hoạch có 3 bảng) và **tài liệu B** (10 trang, 1.666 từ, 8.810 ký tự, văn bản mẫu có mục lục, đầu trang và chân trang lặp lại). Bản 42/120 trang gọi là "tài liệu B đầy đủ". Số từ và ký tự đếm trên đáp án sau chuẩn hóa (`so_sanh_thu_tu_doc_2026-10-19_*.json`). Đã đổi ở Tóm tắt, 3.6, TC19, 3.9, 3.10 (Bảng 3-7 đến 3-10), Kết luận và slide 19, 20, 24. Mã định danh `decuong4`/`decuong_v4` trong ảnh chụp và đoạn trích được giữ nguyên. Các chỗ "đề cương" nói về kế hoạch và mục tiêu đồ án cũng giữ nguyên.
- Mốc thời gian theo kế hoạch triển khai ĐATN năm học 2026-2027 do người dùng cung cấp:
  - Thực hiện 24/08–08/11/2026 (11 tuần); GVHD kiểm tra khối lượng 08/11.
  - Nộp báo cáo 09/11; phản biện 10–15/11; lập hội đồng 16–22/11; bảo vệ dự kiến 23–29/11/2026.
  - Đã sửa câu ở Mở đầu, đoạn dẫn và Bảng 1-4 (14 tuần; nội dung tuần 8–10 khớp ngày thật trong nhật ký). Slide không có lịch.
  - GVHD vẫn là ThS. Ngô Hùng Long; các cô có tên trong bảng kế hoạch là cán bộ Bộ môn, không phải GVHD.
- Lời cảm ơn ghi ngày 09/11/2026; gáy ghi "CNPM K67 05A – ĐỢT KỲ 1A".
- 26/10 chiều: người dùng chuyển hệ thống sang **GPU** (image layout-worker-gpu, vietocr-worker-gpu đã có sẵn, không build lại). Quay về CPU: `docker compose up -d --no-deps layout_detector vietocr`.
- Lỗi tên tệp có dấu tiếng Việt: preprocess sập 500 khi đặt header `X-Document-Id`. Đã sửa web_ui (bỏ dấu tên tệp) và preprocess (tên không phải ASCII trả 422), đã build lại hai container và kiểm tra lại. Chi tiết trong `tools/results/kiem_thu_2026-10-26.md`. Báo cáo đã cập nhật:
  - mục 3.5.1 thêm lỗi (xi);
  - UC01 bước 4, mục 3.4.1 và 3.4.5 ghi việc bỏ dấu / kiểm tra tên tệp;
  - Bảng 2-12 dòng POST /process thêm lỗi 422.
- Bản trong thư mục người dùng được mở và lưu bằng Word lúc 11:23 thì bị hỏng đánh số Heading 1 ("CHƯƠNG 1. LỜI CẢM ƠN"…, chương thật thành 7–9). Nội dung văn bản không khác gì ngoài lỗi này. Bản đó được giữ ở `_luu_tru/BaoCao_ban_mo_Word_26-10_11h23.docx` rồi ghi đè bằng bản sửa.

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

0. **Việc nên làm tiếp:** (a) cải thiện dấu tiếng Việt với chữ in (fine-tune VietOCR trên chữ in / hậu xử lý ngôn ngữ) để vượt Tesseract; (b) bộ tài liệu quét thực tế có đáp án; (c) nếu cần số CPU 120 trang đo trực tiếp: để máy rảnh rồi chạy `python bench.py --api http://localhost:8080 --pdf mau120trang.pdf --label cpu_120` trong ocr-web-ui  
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
