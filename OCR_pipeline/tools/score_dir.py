"""
score_dir.py — Chấm một thư mục kết quả page_N.txt với đáp án, dùng đúng hàm score() của eval_ocr.py.

    python score_dir.py --pred-dir tess_decuong4 --gt-dir gt_decuong4 --label "Tesseract 5"
"""
import argparse
import json
import os
import re
from collections import Counter

from eval_ocr import score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred-dir", required=True)
    ap.add_argument("--gt-dir", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--out")
    a = ap.parse_args()

    total, rows = Counter(), []
    for fn in sorted((f for f in os.listdir(a.gt_dir) if f.endswith(".txt")), key=lambda s: int(re.sub(r"\D", "", s) or 0)):
        gt = open(os.path.join(a.gt_dir, fn), encoding="utf-8").read()
        p = os.path.join(a.pred_dir, fn)
        pred = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        s = score(pred, gt)
        rows.append({"page": fn[:-4], **s})
        for k in ("gt_chars", "char_edits", "gt_words", "word_edits", "pred_words", "common_words"):
            total[k] += s[k]
    prec = total["common_words"] / total["pred_words"] if total["pred_words"] else 0
    rec = total["common_words"] / total["gt_words"] if total["gt_words"] else 0
    overall = {"cer": total["char_edits"] / total["gt_chars"], "wer": total["word_edits"] / total["gt_words"],
               "word_precision": prec, "word_recall": rec, "word_f1": 2 * prec * rec / (prec + rec) if prec + rec else 0}
    print(f"{a.label:<28} CER {overall['cer']:7.2%}  WER {overall['wer']:7.2%}  "
          f"P {prec:7.2%}  R {rec:7.2%}  F1 {overall['word_f1']:7.2%}")
    if a.out:
        json.dump({"label": a.label, "overall": overall, "pages": rows}, open(a.out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
