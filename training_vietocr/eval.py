"""
eval.py — Đánh giá model chi tiết: CER, WER, acc_full_seq, acc_per_char.
In bảng ký tự sai nhiều nhất → biết cần thêm data gì.

Dùng:
    python eval.py
    python eval.py --model weights/transformerocr_v2.pth --split val
    python eval.py --n 500          # chỉ eval 500 mẫu (nhanh hơn)
    python eval.py --show-worst 20  # xem 20 mẫu tệ nhất
"""
import argparse
import json
import os
from collections import Counter
from pathlib import Path

from PIL import Image
from vietocr.tool.config import Cfg
from vietocr.tool.predictor import Predictor

try:
    import editdistance
    ED_OK = True
except ImportError:
    ED_OK = False
    print("⚠ pip install editdistance")

try:
    from rich.table import Table
    from rich.console import Console
    from rich import box
    RICH_OK = True
    console = Console()
except ImportError:
    RICH_OK = False


# ── Metrics ──────────────────────────────────────────────────────────────────

def cer(pred: str, gt: str) -> float:
    if not gt: return 0.0 if not pred else 1.0
    return editdistance.eval(list(pred), list(gt)) / len(gt)

def wer(pred: str, gt: str) -> float:
    gw, pw = gt.split(), pred.split()
    if not gw: return 0.0 if not pw else 1.0
    return editdistance.eval(pw, gw) / len(gw)

def full_seq_acc(pred: str, gt: str) -> bool:
    return pred.strip() == gt.strip()


# ── Char confusion ────────────────────────────────────────────────────────────

def char_errors(pred: str, gt: str) -> list[tuple[str, str]]:
    """Trả về list (gt_char, pred_char) bị nhầm."""
    errors = []
    for i in range(min(len(pred), len(gt))):
        if pred[i] != gt[i]:
            errors.append((gt[i], pred[i]))
    for c in gt[len(pred):]:   errors.append((c, "<DEL>"))
    for c in pred[len(gt):]:   errors.append(("<INS>", c))
    return errors


# ── Load model ────────────────────────────────────────────────────────────────

def load_predictor(model_path: str, vocab_path: str, device: str) -> Predictor:
    config = Cfg.load_config_from_name("vgg_transformer")
    with open(vocab_path, encoding="utf-8") as f:
        config["vocab"] = f.read()
    config["weights"] = model_path
    config["device"]  = device
    config["predictor"]["beamsearch"] = False
    return Predictor(config)


# ── Main eval ─────────────────────────────────────────────────────────────────

def run_eval(args) -> dict:
    # Chọn model/vocab
    model_path = args.model or (
        "./weights/transformerocr_v2.pth"
        if os.path.exists("./weights/transformerocr_v2.pth")
        else "./weights/transformerocr_handwriting.pth"
    )
    vocab_path = args.vocab or (
        "vocab_v2.txt" if os.path.exists("vocab_v2.txt") else "vocab_v1.txt"
    )

    print(f"📦 Model: {model_path}")
    print(f"📝 Vocab: {vocab_path}")

    if not os.path.exists(model_path):
        print(f"❌ Không tìm thấy model: {model_path}")
        return {}

    predictor = load_predictor(model_path, vocab_path, args.device)

    # Đọc annotation
    data_root = "./vietocr_data/"
    ann_file  = os.path.join(data_root, f"{args.split}_annotation.txt")
    if not os.path.exists(ann_file):
        print(f"Không tìm thấy: {ann_file}")
        return {}

    samples = []
    with open(ann_file, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if "\t" not in line: continue
            img_rel, gt = line.split("\t", 1)
            img_path = os.path.join(data_root, img_rel)
            if os.path.exists(img_path):
                samples.append((img_path, gt))

    if args.n:
        import random; random.seed(42)
        samples = random.sample(samples, min(args.n, len(samples)))

    print(f"Evaluating {len(samples)} samples (split={args.split})...\n")

    all_cer, all_wer, all_full = [], [], []
    confusion = Counter()
    worst = []

    for i, (img_path, gt) in enumerate(samples):
        if i % 100 == 0:
            print(f"  [{i}/{len(samples)}]", end="\r")
        try:
            img  = Image.open(img_path).convert("RGB")
            pred = predictor.predict(img)
        except Exception as e:
            pred = ""

        c = cer(pred, gt) if ED_OK else 0
        w = wer(pred, gt) if ED_OK else 0
        a = full_seq_acc(pred, gt)

        all_cer.append(c)
        all_wer.append(w)
        all_full.append(int(a))

        if c > 0:
            for pair in char_errors(pred, gt):
                confusion[pair] += 1
            worst.append({"img": img_path, "gt": gt, "pred": pred, "cer": c})

    # Tổng hợp
    n          = len(all_cer)
    mean_cer   = sum(all_cer) / n
    mean_wer   = sum(all_wer) / n
    acc_full   = sum(all_full) / n
    acc_char   = 1 - mean_cer

    target_met = acc_full >= 0.60

    print("\n" + "=" * 55)
    print(f"  {'MỤC TIÊU ĐẠT ĐƯỢC ' if target_met else 'CHƯA ĐẠT MỤC TIÊU '}")
    print("=" * 55)
    print(f"  acc_full_seq : {acc_full:.4f}  (target ≥ 0.60, hiện tại v1: 0.3457)")
    print(f"  acc_per_char : {acc_char:.4f}  (target ≥ 0.90, hiện tại v1: 0.8298)")
    print(f"  CER          : {mean_cer:.4f}")
    print(f"  WER          : {mean_wer:.4f}")
    print(f"  Samples      : {n}")
    print("=" * 55)

    # Bảng ký tự sai nhiều nhất
    print(f"\nTop 20 ký tự bị nhầm nhiều nhất:")
    print(f"  {'GT':<8} {'Pred':<12} {'Số lần'}")
    print("  " + "-" * 30)
    for (gt_c, pred_c), cnt in confusion.most_common(20):
        print(f"  {repr(gt_c):<8} {repr(pred_c):<12} {cnt}")

    # Worst samples
    worst.sort(key=lambda x: x["cer"], reverse=True)
    if args.show_worst > 0:
        print(f"\n❌ Top {args.show_worst} mẫu tệ nhất:")
        print(f"  {'GT':<35} {'Pred':<35} CER")
        print("  " + "-" * 78)
        for w in worst[:args.show_worst]:
            print(f"  {w['gt'][:35]:<35} {w['pred'][:35]:<35} {w['cer']:.3f}")

    # Xuất JSON
    os.makedirs("./outputs", exist_ok=True)
    report = {
        "model": model_path, "split": args.split, "n_samples": n,
        "acc_full_seq": round(acc_full, 4),
        "acc_per_char": round(acc_char, 4),
        "mean_cer": round(mean_cer, 4),
        "mean_wer": round(mean_wer, 4),
        "target_met": target_met,
        "top_char_errors": {f"{g}→{p}": c for (g, p), c in confusion.most_common(50)},
        "worst_samples": [{"gt": w["gt"], "pred": w["pred"],
                           "cer": round(w["cer"], 4)} for w in worst[:100]],
    }
    out_path = "./outputs/eval_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Worst samples cho hard mining
    worst_txt = "./outputs/worst_samples.txt"
    with open(worst_txt, "w", encoding="utf-8") as f:
        for w in worst:
            f.write(f"{w['img']}\t{w['gt']}\n")

    print(f"\nBáo cáo: {out_path}")
    print(f"Hard samples: {worst_txt}")

    return report


def main():
    p = argparse.ArgumentParser(description="Eval VietOCR v2")
    p.add_argument("--model",       default=None)
    p.add_argument("--vocab",       default=None)
    p.add_argument("--split",       default="val", choices=["train", "val"])
    p.add_argument("--n",           type=int, default=None, help="Số mẫu eval (None = tất cả)")
    p.add_argument("--show-worst",  type=int, default=10)
    p.add_argument("--device",      default="cuda:0")
    args = p.parse_args()

    if not ED_OK:
        print("Cần cài: pip install editdistance")
        return

    run_eval(args)


if __name__ == "__main__":
    main()