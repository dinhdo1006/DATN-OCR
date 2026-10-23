import os
from pdf2image import convert_from_path, pdfinfo_from_path
import cv2
import numpy as np

def process_scan_pdf(pdf_path, output_dir):

    os.makedirs(output_dir, exist_ok=True)

    # Chuyển từng trang một thay vì cả tệp: ảnh 300 DPI của một trang A4 khoảng 26 MB,
    # nạp cùng lúc cả tài liệu 120 trang cần hơn 3 GB RAM và làm máy hết bộ nhớ
    total = pdfinfo_from_path(pdf_path)["Pages"]

    paths = []

    for i in range(total):

        page = convert_from_path(pdf_path, dpi=300, first_page=i + 1, last_page=i + 1)[0]

        img = np.array(page)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        img = cv2.resize(img, None, fx=1.2, fy=1.2)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        out = os.path.join(output_dir, f"page_{i+1}.png")

        cv2.imwrite(out, gray)

        paths.append(out)

    return paths
