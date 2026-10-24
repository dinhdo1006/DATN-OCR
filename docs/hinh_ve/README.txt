Mã nguồn các hình vẽ trong báo cáo (SVG vẽ bằng JavaScript, mở trực tiếp bằng trình duyệt).

- figX_Y.html  -> Hình X-Y; figX_Y.png là ảnh đã chèn vào báo cáo.
- dg.js        -> bộ vẽ sơ đồ khối dùng chung (hộp, elip, mũi tên, chữ).
- seq.js       -> bộ vẽ biểu đồ tuần tự UML (Hình 2-9, 2-10, 2-11).
- gen_fig3_1.sh -> dựng Hình 3-1 từ kết quả docker compose ps (tệp ps.txt).

Quy ước cỡ chữ: hình rộng 880 px được chèn rộng 439 pt (đủ khổ trang), nên chữ 16 px in ra khoảng 8 pt,
chữ nhỏ nhất 14 px khoảng 7 pt.

Xuất PNG (độ phân giải gấp đôi), ví dụ Hình 2-7 cao 520 px:
  msedge --headless=new --force-device-scale-factor=2 --window-size=880,520 --hide-scrollbars ^
         --screenshot=fig2_7.png file:///<đường dẫn>/fig2_7.html
