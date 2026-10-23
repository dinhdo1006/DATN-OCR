"""
baseline_ocr.py — Chạy OCR đối chứng trên đúng ảnh trang mà pipeline dùng (pic/raw/<id>/page_N.png).

Ghi ra <out-dir>/page_N.txt để chấm bằng score_dir.py với cùng đáp án như eval_ocr.py.

    # Tesseract 5 (gói vie), tự phân tích bố cục (psm 3)
    python baseline_ocr.py --engine tesseract --img-dir pic_decuong4 --out-dir tess_decuong4

    # PaddleOCR đủ hai bước phát hiện + nhận dạng (mô hình latin/vi), không dùng VietOCR, không phân tích bố cục
    python baseline_ocr.py --engine paddle --img-dir pic_decuong4 --out-dir paddle_decuong4

    # Không phân tích bố cục: DBNet tìm dòng trên cả trang, VietOCR nhận dạng, sắp dòng theo (y, x)
    python baseline_ocr.py --engine nolayout-detect --img-dir ... --out-dir crops_x   (container paddleocr)
    python baseline_ocr.py --engine nolayout-recog  --img-dir crops_x --out-dir nolayout_x (container vietocr)
"""
import argparse
import json
import os
import re
import subprocess
import time


def pages(img_dir):
    fs = [f for f in os.listdir(img_dir) if re.fullmatch(r"page_\d+\.png", f)]
    return sorted(fs, key=lambda f: int(re.sub(r"\D", "", f)))


def run_tesseract(img_dir, out_dir):
    for f in pages(img_dir):
        stem = os.path.splitext(f)[0]
        subprocess.run(["tesseract", os.path.join(img_dir, f), os.path.join(out_dir, stem), "-l", "vie", "--psm", "3"],
                       check=True, capture_output=True)


def paddle_lines(ocr, path):
    res = ocr.ocr(path, cls=False)
    lines = []
    for item in (res[0] or []):
        box, (text, _conf) = item
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        lines.append((min(ys), min(xs), max(ys) - min(ys), text))
    return lines


def order_lines(lines):
    """Gom các box cùng hàng (lệch tâm < nửa chiều cao trung bình) rồi đọc trái sang phải."""
    if not lines:
        return []
    h = sum(l[2] for l in lines) / len(lines)
    lines = sorted(lines, key=lambda l: (l[0] + l[2] / 2, l[1]))
    rows, cur, cy = [], [], None
    for l in lines:
        c = l[0] + l[2] / 2
        if cy is None or abs(c - cy) < 0.5 * h:
            cur.append(l)
        else:
            rows.append(cur)
            cur = [l]
        cy = sum(x[0] + x[2] / 2 for x in cur) / len(cur)
    rows.append(cur)
    return [" ".join(x[3] for x in sorted(r, key=lambda x: x[1])) for r in rows]


def run_paddle(img_dir, out_dir):
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(lang="vi", use_angle_cls=False, show_log=False)
    for f in pages(img_dir):
        text = "\n".join(order_lines(paddle_lines(ocr, os.path.join(img_dir, f))))
        with open(os.path.join(out_dir, os.path.splitext(f)[0] + ".txt"), "w", encoding="utf-8") as fh:
            fh.write(text)


def run_nolayout_detect(img_dir, out_dir):
    """DBNet trên cả trang (không qua DocLayout-YOLO), cắt từng dòng như paddleocr-worker."""
    import cv2
    import numpy as np
    from paddleocr import PaddleOCR
    det = PaddleOCR(lang="en", use_angle_cls=False, rec=False, show_log=False)
    for f in pages(img_dir):
        stem = os.path.splitext(f)[0]
        img = cv2.imread(os.path.join(img_dir, f))
        boxes = det.ocr(img, rec=False, cls=False)[0] or []
        meta = []
        for i, box in enumerate(boxes):
            pts = np.array(box, dtype="float32")
            w = int(max(np.linalg.norm(pts[0] - pts[1]), np.linalg.norm(pts[2] - pts[3])))
            h = int(max(np.linalg.norm(pts[0] - pts[3]), np.linalg.norm(pts[1] - pts[2])))
            if w < 4 or h < 4:
                continue
            M = cv2.getPerspectiveTransform(pts, np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype="float32"))
            crop = cv2.warpPerspective(img, M, (w, h))
            name = f"{stem}_{i}.png"
            cv2.imwrite(os.path.join(out_dir, name), crop)
            ys, xs = [p[1] for p in box], [p[0] for p in box]
            meta.append({"file": name, "y": min(ys), "x": min(xs), "h": max(ys) - min(ys)})
        with open(os.path.join(out_dir, stem + ".json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh)


def run_nolayout_recog(img_dir, out_dir):
    """VietOCR (cùng trọng số với vietocr-worker) nhận dạng các dòng đã cắt, rồi sắp theo (y, x)."""
    from PIL import Image
    from vietocr.tool.config import Cfg
    from vietocr.tool.predictor import Predictor
    cfg = Cfg.load_config_from_file("/app/config_handwriting_final.yml")
    cfg["weights"] = "/app/weights/transformerocr_final.pth"
    cfg["cnn"]["pretrained"] = False
    cfg["device"] = os.getenv("DEVICE", "cpu")
    cfg["predictor"]["beamsearch"] = False
    rec = Predictor(cfg)
    for jf in sorted(f for f in os.listdir(img_dir) if f.endswith(".json")):
        meta = json.load(open(os.path.join(img_dir, jf), encoding="utf-8"))
        lines = []
        for m in meta:
            text = rec.predict(Image.open(os.path.join(img_dir, m["file"])).convert("RGB"))
            lines.append((m["y"], m["x"], m["h"], text))
        with open(os.path.join(out_dir, jf.replace(".json", ".txt")), "w", encoding="utf-8") as fh:
            fh.write("\n".join(order_lines(lines)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, choices=["tesseract", "paddle", "nolayout-detect", "nolayout-recog"])
    ap.add_argument("--img-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    t0 = time.time()
    {"tesseract": run_tesseract, "paddle": run_paddle,
     "nolayout-detect": run_nolayout_detect, "nolayout-recog": run_nolayout_recog}[a.engine](a.img_dir, a.out_dir)
    print(f"{a.engine}: {a.img_dir} -> {a.out_dir} trong {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
