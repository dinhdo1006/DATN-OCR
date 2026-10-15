"""
prepare_company_data.py — Convert data công ty sang VietOCR format
rồi merge với data 5CD-AI để fine-tune.

Format input:
    Data_line_processed/image_name.png  ← ảnh
    Data_line_processed/image_name.txt  ← 1 dòng text label

Format output (VietOCR):
    img_path<TAB>label text

Dùng:
    python prepare_company_data.py
"""
import os
import random
import shutil
from pathlib import Path


DATA_DIR     = "./vietocr_data/Data_line_processed"
VIETOCR_DATA = "./vietocr_data"
TRAIN_ANN    = os.path.join(VIETOCR_DATA, "train_annotation.txt")
VAL_ANN      = os.path.join(VIETOCR_DATA, "val_annotation.txt")

# Split ratio cho data công ty
VAL_RATIO    = 0.15   # 15% làm val (~600 mẫu)
RANDOM_SEED  = 42


def load_company_data(data_dir: str) -> list[tuple[str, str]]:
    """
    Đọc tất cả cặp (png, txt) từ thư mục.
    Trả về list (absolute_img_path, label_text).
    """
    data_dir = Path(data_dir)
    samples  = []
    skipped  = 0

    png_files = sorted(data_dir.glob("*.png"))
    print(f"Tìm thấy {len(png_files)} file PNG")

    for png_path in png_files:
        txt_path = png_path.with_suffix(".txt")

        if not txt_path.exists():
            skipped += 1
            continue

        # Đọc label — lấy dòng đầu tiên, strip whitespace
        label = txt_path.read_text(encoding="utf-8").strip().split("\n")[0].strip()

        if not label:
            skipped += 1
            continue

        samples.append((str(png_path.resolve()), label))

    print(f"✅ Hợp lệ : {len(samples)} cặp ảnh+label")
    print(f"⏭  Bỏ qua: {skipped} (không có txt hoặc label rỗng)")
    return samples


def check_vocab_coverage(samples: list, vocab: set) -> tuple[list, list]:
    """
    Lọc sample: chỉ giữ label có ký tự nằm trong vocab.
    Trả về (ok_samples, skipped_samples).
    """
    ok      = []
    skipped = []
    missing_chars = set()

    for img_path, label in samples:
        bad = [c for c in label if c not in vocab]
        if bad:
            missing_chars.update(bad)
            skipped.append((img_path, label))
        else:
            ok.append((img_path, label))

    if missing_chars:
        print(f"⚠  {len(skipped)} sample bị lọc do ký tự ngoài vocab: "
              f"{sorted(missing_chars)[:20]}")
    return ok, skipped


def read_existing_annotation(ann_file: str) -> list[str]:
    """Đọc file annotation hiện tại."""
    if not os.path.exists(ann_file):
        return []
    with open(ann_file, encoding="utf-8") as f:
        return [l for l in f.readlines() if l.strip()]


def write_annotation(lines: list[str], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def main():
    print("=" * 60)
    print("  Chuẩn bị data công ty để fine-tune VietOCR")
    print("=" * 60)

    # Load vocab hiện tại
    from vietocr.tool.config import Cfg
    config = Cfg.load_config_from_file("config_handwriting.yml")
    vocab  = set(config["vocab"])
    print(f"\n Vocab hiện tại: {len(vocab)} ký tự")

    # Load data công ty
    print(f"\n📂 Đọc data từ: {DATA_DIR}")
    samples = load_company_data(DATA_DIR)

    if not samples:
        print("❌ Không có sample nào hợp lệ!")
        return

    # Kiểm tra vocab coverage
    print(f"\nKiểm tra vocab coverage...")
    ok_samples, _ = check_vocab_coverage(samples, vocab)
    print(f"✅ Dùng được: {len(ok_samples)}/{len(samples)} samples")

    if not ok_samples:
        print("❌ Không có sample nào pass vocab check!")
        return

    # Shuffle và split
    random.seed(RANDOM_SEED)
    random.shuffle(ok_samples)

    n_val   = max(1, int(len(ok_samples) * VAL_RATIO))
    n_train = len(ok_samples) - n_val

    company_val   = ok_samples[:n_val]
    company_train = ok_samples[n_val:]

    print(f"\n✂  Split data công ty:")
    print(f"   Train: {n_train} samples")
    print(f"   Val  : {n_val} samples")

    # Convert sang VietOCR format
    def to_vietocr_line(img_path: str, label: str) -> str:
        return f"{img_path}\t{label.replace(chr(9), ' ')}\n"

    company_train_lines = [to_vietocr_line(p, l) for p, l in company_train]
    company_val_lines   = [to_vietocr_line(p, l) for p, l in company_val]

    # Đọc annotation hiện tại (5CD-AI data)
    existing_train = read_existing_annotation(TRAIN_ANN)
    existing_val   = read_existing_annotation(VAL_ANN)

    print(f"\nData hiện tại (5CD-AI):")
    print(f"   Train: {len(existing_train):,} samples")
    print(f"   Val  : {len(existing_val):,} samples")

    # Backup annotation cũ
    for f, bak in [(TRAIN_ANN, TRAIN_ANN + ".bak"),
                   (VAL_ANN,   VAL_ANN   + ".bak")]:
        if os.path.exists(f):
            shutil.copy(f, bak)
    print(f"\nĐã backup annotation cũ (.bak)")

    # Merge: company data + 5CD-AI data
    # Đặt company data LÊN TRƯỚC để model ưu tiên học domain này
    merged_train = company_train_lines + existing_train
    merged_val   = company_val_lines   + existing_val

    write_annotation(merged_train, TRAIN_ANN)
    write_annotation(merged_val,   VAL_ANN)

    print(f"\nĐã merge và ghi annotation mới:")
    print(f"   Train: {len(merged_train):,} samples "
          f"({n_train} công ty + {len(existing_train):,} 5CD-AI)")
    print(f"   Val  : {len(merged_val):,} samples "
          f"({n_val} công ty + {len(existing_val):,} 5CD-AI)")

    print(f"""
{'=' * 60}
  Bước tiếp theo: Fine-tune từ model final
{'=' * 60}
  python train_finetune.py

  Mục tiêu sau fine-tune:
    acc_full_seq > 0.50  (từ 0.3528 hiện tại)
    confidence trên ảnh công ty > 85%
{'=' * 60}
""")


if __name__ == "__main__":
    main()