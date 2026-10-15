"""
Inference_v2.py — Inference với model v2.

Cải tiến so với Inference.py cũ:
  - Tự động fallback về model v1 nếu v2 chưa có
  - Batch prediction (nhiều ảnh cùng lúc)
  - In confidence rõ hơn: màu đỏ nếu thấp
  - Có thể chạy trên cả thư mục ảnh

Dùng:
    # Test 1 ảnh
    python Inference_v2.py --image anh_test.png

    # Test cả thư mục
    python Inference_v2.py --dir ./test_images/

    # Dùng model cụ thể
    python Inference_v2.py --image a.png --model weights/transformerocr_v2.pth
"""
import os
import argparse
from pathlib import Path
from PIL import Image

from vietocr.tool.predictor import Predictor
from vietocr.tool.config import Cfg

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def load_predictor(model_path: str, vocab_path: str, device: str = "cuda:0") -> Predictor:
    config = Cfg.load_config_from_name("vgg_transformer")

    # Load vocab
    if not os.path.exists(vocab_path):
        raise FileNotFoundError(
            f"Không tìm thấy vocab: {vocab_path}\n"
            "Chạy train_v2.py trước để tạo vocab_v2.txt"
        )
    with open(vocab_path, encoding="utf-8") as f:
        config["vocab"] = f.read()

    config["weights"]               = model_path
    config["device"]                = device
    config["predictor"]["beamsearch"] = False   # False = nhanh hơn, đủ dùng

    print(f"⚙  Model:  {model_path}")
    print(f"⚙  Vocab:  {vocab_path} ({len(config['vocab'])} ký tự)")
    print(f"⚙  Device: {device}")

    return Predictor(config)


def predict_one(predictor: Predictor, img_path: str) -> tuple[str, float]:
    img = Image.open(img_path).convert("RGB")
    text, prob = predictor.predict(img, return_prob=True)
    return text, prob


def format_confidence(prob: float) -> str:
    if prob >= 0.90:
        return f"✅ {prob:.2%}"
    elif prob >= 0.70:
        return f"⚠  {prob:.2%}"
    else:
        return f"❌ {prob:.2%} (thấp)"


def run_single(predictor: Predictor, img_path: str) -> None:
    if not os.path.exists(img_path):
        print(f"❌ Không tìm thấy ảnh: {img_path}")
        return
    text, prob = predict_one(predictor, img_path)
    print("\n" + "=" * 50)
    print(f"  Ảnh:       {Path(img_path).name}")
    print(f"  Kết quả:   {text}")
    print(f"  Confidence:{format_confidence(prob)}")
    print("=" * 50)


def run_directory(predictor: Predictor, dir_path: str) -> None:
    images = [
        p for p in Path(dir_path).iterdir()
        if p.suffix.lower() in IMAGE_EXTS
    ]
    if not images:
        print(f"❌ Không có ảnh nào trong {dir_path}")
        return

    print(f"\n📂 {len(images)} ảnh trong {dir_path}\n")
    print(f"{'Tên ảnh':<40} {'Kết quả':<35} {'Confidence'}")
    print("-" * 95)

    ok = warn = fail = 0
    for img_path in sorted(images):
        try:
            text, prob = predict_one(predictor, str(img_path))
            conf_str = format_confidence(prob)
            print(f"{img_path.name:<40} {text[:35]:<35} {conf_str}")
            if prob >= 0.90:   ok   += 1
            elif prob >= 0.70: warn += 1
            else:              fail += 1
        except Exception as exc:
            print(f"{img_path.name:<40} {'[LỖI]':<35} {exc}")
            fail += 1

    print("-" * 95)
    print(f"✅ Cao (≥90%): {ok}  ⚠ Trung bình (70-90%): {warn}  ❌ Thấp (<70%): {fail}")


def main():
    p = argparse.ArgumentParser(description="Inference VietOCR v2")
    p.add_argument("--image",  type=str, default=None, help="Path tới 1 ảnh")
    p.add_argument("--dir",    type=str, default=None, help="Thư mục chứa nhiều ảnh")
    p.add_argument("--model",  type=str, default=None, help="Override model path")
    p.add_argument("--vocab",  type=str, default=None, help="Override vocab path")
    p.add_argument("--device", type=str, default="cuda:0")
    args = p.parse_args()

    # Tự động chọn model và vocab: ưu tiên v3 nếu có
    if args.model:
        model_path = args.model
    elif os.path.exists("./weights/transformerocr_v2.pth"):
        model_path = "./weights/transformerocr_v2.pth"
        print("▶  Dùng model v2 (mới)")
    else:
        model_path = "./weights/transformerocr_handwriting.pth"
        print("▶  Dùng model v1 (v2 chưa train xong)")

    if args.vocab:
        vocab_path = args.vocab
    elif os.path.exists("vocab_v2.txt"):
        vocab_path = "vocab_v2.txt"
    else:
        vocab_path = "vocab_v1.txt"

    predictor = load_predictor(model_path, vocab_path, args.device)

    if args.dir:
        run_directory(predictor, args.dir)
    elif args.image:
        run_single(predictor, args.image)
    else:
        # Demo mode — tìm ảnh bất kỳ trong thư mục hiện tại
        sample_images = list(Path(".").glob("*.png")) + list(Path(".").glob("*.jpg"))
        if sample_images:
            print(f"🔍 Tìm thấy {len(sample_images)} ảnh, test ảnh đầu tiên:")
            run_single(predictor, str(sample_images[0]))
        else:
            print("⚠  Không có ảnh test. Dùng:")
            print("   python Inference.py --image YOUR_IMAGE.png")
            print("   python Inference.py --dir ./test_images/")


if __name__ == "__main__":
    main()