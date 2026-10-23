"""
degrade_pdf.py — Tạo bản "quét mô phỏng" của một PDF để đánh giá OCR trên ảnh chất lượng thấp.

Mỗi trang: rasterize 200 DPI, ảnh xám, nghiêng ngẫu nhiên ±1,2°, làm mờ Gauss (σ = 1), nhiễu Gauss (σ = 12),
đốm bẩn, giảm tương phản, nén JPEG chất lượng 35, rồi ghép lại thành PDF ảnh (không còn lớp chữ).
Seed cố định nên chạy lại cho đúng cùng một bản. Đáp án giữ nguyên lớp chữ của PDF gốc (pdftotext).

    python degrade_pdf.py --src decuong4.pdf --dst decuong4_quet.pdf
"""
import argparse
import io

import cv2
import numpy as np
from pdf2image import convert_from_path
from PIL import Image


def degrade(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    h, w = img.shape
    angle = rng.uniform(-1.2, 1.2)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    img = cv2.warpAffine(img, M, (w, h), borderValue=255)
    img = cv2.GaussianBlur(img, (3, 3), 1.0)
    img = img.astype(np.float32) * 0.85 + 25                      # giảm tương phản, nền hơi xám
    img += rng.normal(0, 12, img.shape)                          # nhiễu cảm biến
    for _ in range(int(h * w / 40000)):                          # đốm bẩn
        y, x = rng.integers(0, h), rng.integers(0, w)
        cv2.circle(img, (int(x), int(y)), int(rng.integers(1, 3)), float(rng.uniform(60, 160)), -1)
    img = np.clip(img, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 35])
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    pages = []
    for page in convert_from_path(a.src, dpi=a.dpi):
        gray = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2GRAY)
        pages.append(Image.fromarray(degrade(gray, rng)))
    pages[0].save(a.dst, save_all=True, append_images=pages[1:], resolution=a.dpi)
    print(f"{a.src} -> {a.dst}: {len(pages)} trang")


if __name__ == "__main__":
    main()
