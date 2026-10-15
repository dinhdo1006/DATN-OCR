"""
eval_ocr.py — Đánh giá pipeline OCR: độ chính xác, thời gian xử lý, CPU/RAM.

Chỉ dùng thư viện chuẩn Python (gọi Web UI qua HTTP, gọi `docker stats` để lấy CPU/RAM).

Văn bản đáp án (ground truth) cho PDF xuất từ văn bản số lấy bằng pdftotext
(có sẵn trong container preprocess):

    docker cp file.pdf preprocess:/tmp/ref.pdf
    for p in 1 2 3; do docker exec preprocess pdftotext -f $p -l $p -enc UTF-8 /tmp/ref.pdf - > gt/page_$p.txt; done

Dùng:
    # upload + đo thời gian + CPU/RAM + độ chính xác
    python eval_ocr.py --upload file.pdf --gt-dir gt/

    # chỉ đánh giá một tài liệu đã xử lý xong
    python eval_ocr.py --doc-id file --gt-dir gt/

Chỉ số:
    CER, WER        : khoảng cách chỉnh sửa / độ dài đáp án (phụ thuộc thứ tự đọc)
    word P / R / F1 : so khớp tập từ, không phụ thuộc thứ tự (bảng nhiều cột làm
                      thứ tự đọc của pdftotext khác OCR nên CER bị phóng đại)
"""
import argparse
import json
import os
import re
import subprocess
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid
from collections import Counter

OCR_CONTAINERS = [
    "preprocess", "layout-worker", "paddleocr-worker", "vietocr-worker",
    "reconstruct-worker", "merge-worker", "nifi", "kafka", "minio",
]


# =====================================================
# HTTP
# =====================================================
def api_get(api, path):
    with urllib.request.urlopen(api + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def upload(api, pdf_path):
    boundary = uuid.uuid4().hex
    name = os.path.basename(pdf_path)
    with open(pdf_path, "rb") as f:
        data = f.read()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        api + "/api/upload", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))["id"]


# =====================================================
# CPU / RAM
# =====================================================
def parse_mem(s):
    """'1.2GiB / 7.6GiB' -> MiB đang dùng."""
    used = s.split("/")[0].strip()
    m = re.match(r"([\d.]+)\s*([KMG]i?B|B)", used)
    if not m:
        return 0.0
    val, unit = float(m.group(1)), m.group(2)
    return val * {"B": 1 / 1048576, "KiB": 1 / 1024, "KB": 1 / 1024,
                  "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1024}[unit]


class StatsSampler(threading.Thread):
    def __init__(self, interval=3):
        super().__init__(daemon=True)
        self.interval = interval
        self.samples = {}  # name -> list[(cpu%, mem MiB)]
        self._halt = threading.Event()

    def run(self):
        while not self._halt.is_set():
            try:
                out = subprocess.run(
                    ["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"]
                    + OCR_CONTAINERS,
                    capture_output=True, text=True, timeout=60,
                ).stdout
                for line in out.strip().splitlines():
                    name, cpu, mem = line.split("|")
                    self.samples.setdefault(name, []).append(
                        (float(cpu.strip("%") or 0), parse_mem(mem))
                    )
            except Exception:
                pass
            self._halt.wait(self.interval)

    def stop(self):
        self._halt.set()

    def summary(self):
        rows = {}
        for name, vals in self.samples.items():
            cpus = [v[0] for v in vals]
            mems = [v[1] for v in vals]
            rows[name] = {
                "cpu_avg": round(sum(cpus) / len(cpus), 1),
                "cpu_max": round(max(cpus), 1),
                "mem_avg_mib": round(sum(mems) / len(mems), 1),
                "mem_max_mib": round(max(mems), 1),
                "samples": len(vals),
            }
        return rows


# =====================================================
# METRICS
# =====================================================
def normalize(text):
    text = unicodedata.normalize("NFC", text)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("===== PAGE"):
            continue
        if re.fullmatch(r"\|(\s*-+\s*\|)+", line):       # dòng phân cách tiêu đề bảng Markdown
            continue
        line = re.sub(r"(?<!\\)\|", " ", line).replace("\\|", "|")  # dấu cột bảng Markdown
        line = re.sub(r"^(#+|-)\s+", "", line)          # marker Markdown của reconstruct
        line = re.sub(r"\[(FIGURE|TABLE): [^\]]*\]", "", line)  # placeholder ảnh/bảng
        lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def edit_distance(a, b):
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def score(pred, gt):
    p, g = normalize(pred), normalize(gt)
    pw, gw = p.split(), g.split()
    if not g and not p:  # trang trắng: cả đáp án và kết quả đều rỗng là đúng
        return {"gt_chars": 0, "char_edits": 0, "gt_words": 0, "word_edits": 0, "pred_words": 0,
                "common_words": 0, "cer": 0.0, "wer": 0.0, "word_precision": 1.0,
                "word_recall": 1.0, "word_f1": 1.0, "blank": True}
    common = sum((Counter(pw) & Counter(gw)).values())
    prec = common / len(pw) if pw else 0.0
    rec = common / len(gw) if gw else 0.0
    return {
        "gt_chars": len(g),
        "char_edits": edit_distance(p, g),
        "gt_words": len(gw),
        "word_edits": edit_distance(pw, gw),
        "pred_words": len(pw),
        "common_words": common,
        "cer": edit_distance(p, g) / len(g) if g else 0.0,
        "wer": edit_distance(pw, gw) / len(gw) if gw else 0.0,
        "word_precision": prec,
        "word_recall": rec,
        "word_f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
    }


def split_pages(text):
    pages = {}
    for m in re.finditer(r"===== PAGE (\S+) =====\n(.*?)(?=\n===== PAGE |\Z)", text, re.S):
        pages[m.group(1)] = m.group(2)
    return pages


# =====================================================
# MAIN
# =====================================================
def main():
    ap = argparse.ArgumentParser(description="Đánh giá pipeline OCR")
    ap.add_argument("--api", default="http://localhost:8501")
    ap.add_argument("--upload", help="PDF cần upload và đo")
    ap.add_argument("--doc-id", help="tài liệu đã xử lý xong")
    ap.add_argument("--gt-dir", required=True, help="thư mục page_N.txt đáp án")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--out", default="eval_report.json")
    args = ap.parse_args()

    timing, resources = None, None
    if args.upload:
        sampler = StatsSampler()
        sampler.start()
        t0 = time.time()
        doc_id = upload(args.api, args.upload)
        print(f"Uploaded -> {doc_id}")
        while True:
            d = api_get(args.api, f"/api/documents/{urllib.parse.quote(doc_id)}")
            print(f"  {time.time() - t0:6.0f}s  {d['status']:7s} {d['pages_done']}/{d['pages_total']}", flush=True)
            if d["status"] == "done":
                break
            if time.time() - t0 > args.timeout:
                raise SystemExit("Hết thời gian chờ")
            time.sleep(5)
        elapsed = time.time() - t0
        sampler.stop()
        timing = {
            "total_seconds": round(elapsed, 1),
            "pages": d["pages_total"],
            "seconds_per_page": round(elapsed / max(1, d["pages_total"]), 1),
        }
        resources = sampler.summary()
    else:
        doc_id = args.doc_id

    d = api_get(args.api, f"/api/documents/{urllib.parse.quote(doc_id)}")
    pred_pages = split_pages(d["text"])

    rows, total = [], Counter()
    for fn in sorted(os.listdir(args.gt_dir), key=lambda s: int(re.sub(r"\D", "", s) or 0)):
        if not fn.endswith(".txt"):
            continue
        page = os.path.splitext(fn)[0]
        with open(os.path.join(args.gt_dir, fn), encoding="utf-8") as f:
            gt = f.read()
        s = score(pred_pages.get(page, ""), gt)
        rows.append({"page": page, **s})
        for k in ("gt_chars", "char_edits", "gt_words", "word_edits", "pred_words", "common_words"):
            total[k] += s[k]

    prec = total["common_words"] / total["pred_words"] if total["pred_words"] else 0
    rec = total["common_words"] / total["gt_words"] if total["gt_words"] else 0
    overall = {
        "cer": total["char_edits"] / total["gt_chars"],
        "wer": total["word_edits"] / total["gt_words"],
        "word_precision": prec,
        "word_recall": rec,
        "word_f1": 2 * prec * rec / (prec + rec) if prec + rec else 0,
    }

    print(f"\nTài liệu: {doc_id}")
    print(f"{'Trang':<8}{'CER':>8}{'WER':>8}{'P(từ)':>8}{'R(từ)':>8}{'F1':>8}")
    for r in rows:
        if r.get("blank"):
            print(f"{r['page']:<8}{'(trang trắng – đúng, không tính vào tổng)':>40}")
            continue
        print(f"{r['page']:<8}{r['cer']:>8.2%}{r['wer']:>8.2%}{r['word_precision']:>8.2%}"
              f"{r['word_recall']:>8.2%}{r['word_f1']:>8.2%}")
    print(f"{'TỔNG':<8}{overall['cer']:>8.2%}{overall['wer']:>8.2%}{overall['word_precision']:>8.2%}"
          f"{overall['word_recall']:>8.2%}{overall['word_f1']:>8.2%}")

    if timing:
        print(f"\nThời gian: {timing['total_seconds']}s cho {timing['pages']} trang "
              f"({timing['seconds_per_page']}s/trang)")
    if resources:
        print(f"\n{'Container':<22}{'CPU tb':>9}{'CPU max':>9}{'RAM tb':>10}{'RAM max':>10}")
        for name, r in sorted(resources.items()):
            print(f"{name:<22}{r['cpu_avg']:>8}%{r['cpu_max']:>8}%{r['mem_avg_mib']:>8}MB{r['mem_max_mib']:>8}MB")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"doc_id": doc_id, "overall": overall, "pages": rows,
                   "timing": timing, "resources": resources}, f, ensure_ascii=False, indent=2)
    print(f"\nĐã lưu: {args.out}")


if __name__ == "__main__":
    main()
