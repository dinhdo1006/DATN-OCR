# So sánh bộ trọng số VietOCR – 15/10/2026

Mục đích: kiểm tra việc dùng `transformerocr_final.pth` (tinh chỉnh, bộ từ vựng 406 ký tự) có tốt hơn
trọng số gốc `vgg_transformer.pth` của VietOCR (229 ký tự) trên văn bản in hay không.

Cách đo: cùng hệ thống, cùng tài liệu và đáp án như lần đo 08/10 (đáp án `pdftotext` khớp từng ký tự);
chỉ thay trọng số của vietocr-worker, các bước layout / crop / reconstruct giữ nguyên.
Đo bằng `tools/eval_ocr.py`; luồng NiFi được thay bằng script giả lập đúng các bước của template
trong lúc chờ tải image NiFi, nên **thời gian dưới đây chỉ để tham khảo**, không dùng để so tốc độ.

| Tài liệu | Trọng số | CER | WER | P (từ) | R (từ) | F1 (từ) |
|---|---|---|---|---|---|---|
| Đề cương ĐATN, 4 trang có bảng | **transformerocr_final (đang dùng)** | **5,44%** | **15,10%** | **90,46%** | **86,08%** | **88,21%** |
| | vgg_transformer gốc | 11,18% | 23,20% | 82,93% | 82,03% | 82,48% |
| Mẫu trình bày ĐATN, 10 trang | **transformerocr_final (đang dùng)** | **37,87%** | **34,57%** | **82,32%** | **73,23%** | **77,51%** |
| | vgg_transformer gốc | 38,80% | 36,01% | 80,76% | 72,81% | 76,58% |

Kết luận: **giữ `transformerocr_final.pth`** – tốt hơn trên cả hai tài liệu (CER đề cương giảm một nửa).

Lần đo lại với trọng số đang dùng tái lập đúng kết quả 08/10 (đề cương: CER 5,44%, F1 88,21% – trùng
từng chữ số; mẫu 10 trang: CER 37,87% so với 37,83%, chênh do VietOCR nhận dạng theo lô 4 ảnh và
thành phần lô phụ thuộc thời điểm thông điệp đến).

Lỗi đặc trưng của trọng số gốc (đề cương, trang 1):

| Đúng (final) | Trọng số gốc |
|---|---|
| … Quang học (OCR) dựa trên | … Quang học (OCR) dựa trên **thuật thức** |
| Học sâu phục vụ Số hóa Tài liệu Tiếng Việt. | Học sâu phục vụ **số** hóa **tài** liệu **tiếng việt** |
| Tiếng Anh: … Deep Learning-Based … | **Tiêng** Anh: … Deep **Leaming**-Based … |

Trọng số gốc hay sinh thêm từ không có ở cuối dòng ("thuật thức", "thuận thuật"), làm mất chữ hoa
và dấu câu cuối dòng. Chỉ khoảng 25 trên gần 5.000 ký tự đáp án nằm ngoài bộ từ vựng gốc (●, –, ○, •),
nên khác biệt chủ yếu do chất lượng nhận dạng, không phải do thiếu ký tự.

Kết quả chi tiết từng trang: `so_sanh_model_2026-10-15_{final,base}_{decuong4,mau10trang}.json`.
