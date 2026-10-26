Mã nguồn các hình vẽ trong báo cáo (SVG vẽ bằng JavaScript, mở trực tiếp bằng trình duyệt).

- figX_Y.html  -> Hình X-Y; figX_Y.png là ảnh đã chèn vào báo cáo.
- dg.js        -> bộ vẽ sơ đồ khối dùng chung (hộp, elip, mũi tên, chữ); gsProc / gsEnt vẽ tiến trình và
                 tác nhân ngoài theo ký pháp Gane–Sarson cho biểu đồ ngữ cảnh (Hình 2-1) và DFD mức 0 (Hình 2-4).
- seq.js       -> bộ vẽ biểu đồ tuần tự theo ký pháp UML 2.5.1 (Hình 2-9, 2-10, 2-11):
                 'sync' nét liền đầu tam giác đặc (gọi đồng bộ), 'async' nét liền đầu mở (gửi bất đồng bộ),
                 'ret' nét đứt đầu mở (trả về), 'self' lời gọi tự thân có thanh kích hoạt lồng.
                 Thanh kích hoạt của bên nhận lời gọi đồng bộ vẽ tự động tới mũi tên trả về tương ứng;
                 spec.acts là thanh của bên chủ động xử lý; chú giải ký pháp ở chân hình.
                 Khung lồng nhau dùng thuộc tính inset, spec.actors vẽ tác nhân dạng hình người.
- fig2_8       -> biểu đồ thành phần UML (mã nguồn không có lớp: mỗi dịch vụ là một chương trình Python độc lập).
- fig_cum      -> sơ đồ hướng phát triển (máy điều phối + N máy worker), dùng trong slide.
- gen_fig3_1.sh -> dựng Hình 3-1 từ kết quả docker compose ps (tệp ps.txt).
- fig3_3.png  -> ảnh chụp giao diện web, đã cắt bỏ tiêu đề trang và dòng bị cắt dở cuối danh sách
                 (giữ ô tải lên và danh sách tới dòng pdf_hong).
- Hình 3-2, 3-4, 3-5 là ảnh chụp màn hình, không có mã nguồn.

Quy ước cỡ chữ: hình rộng 880 px được chèn rộng 439 pt (đủ khổ trang), nên chữ 16 px in ra khoảng 8 pt,
chữ nhỏ nhất 14 px khoảng 7 pt. Biểu đồ tuần tự rộng 1100–1160 px dùng chữ 21 px (khoảng 8 pt khi in).

Xuất PNG (độ phân giải gấp đôi), ví dụ Hình 2-7 cao 520 px:
  msedge --headless=new --force-device-scale-factor=2 --window-size=880,520 --hide-scrollbars ^
         --screenshot=fig2_7.png file:///<đường dẫn>/fig2_7.html
