"""
train_finetune.py — Fine-tune từ transformerocr_final.pth với data công ty.

Fix so với version cũ:
  - config['pretrain'] thay vì config['weights'] để load weights khi train
    (source VietOCR trainer.py dòng 59: weight_file = download_weights(config['pretrain']))
  - image_max_width: 640 (99.9% ảnh công ty = 523px, tránh crop mất chữ)
"""
import io, math, os, random, sys, types
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance

for _m in ("imgaug", "imgaug.augmenters", "imgaug.augmenters.meta",
           "imgaug.augmenters.arithmetic", "imgaug.augmenters.blur",
           "imgaug.augmenters.contrast", "imgaug.augmenters.geometric"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)

from vietocr.tool.config import Cfg
from vietocr.model.trainer import Trainer


class HandwritingAugmentor:
    def __call__(self, img: Image.Image) -> Image.Image:
        mode = img.mode
        try:
            if random.random() < 0.4:
                img = img.filter(ImageFilter.GaussianBlur(
                    radius=random.uniform(0, 1.5)))
            if random.random() < 0.3:
                arr = np.array(img, dtype=np.float32)
                arr = np.clip(
                    arr + np.random.normal(0, random.uniform(3, 15), arr.shape),
                    0, 255)
                img = Image.fromarray(arr.astype(np.uint8), mode)
            if random.random() < 0.5:
                img = ImageEnhance.Brightness(img).enhance(random.uniform(0.7, 1.3))
            if random.random() < 0.4:
                img = ImageEnhance.Contrast(img).enhance(random.uniform(0.7, 1.4))
            if random.random() < 0.5:
                img = self._affine(img, rotate=random.uniform(-3, 3),
                                   shear=random.uniform(-2, 2))
            if random.random() < 0.3:
                img = img.filter(
                    ImageFilter.MaxFilter(3) if random.random() < 0.5
                    else ImageFilter.MinFilter(3))
            if img.mode != mode:
                img = img.convert(mode)
        except Exception:
            pass
        return img

    @staticmethod
    def _affine(img, rotate, shear):
        try:
            w, h = img.size
            a  = math.cos(math.radians(rotate))
            b  = -math.sin(math.radians(rotate)) \
                 + math.tan(math.radians(shear)) * a
            d  = math.sin(math.radians(rotate))
            e  = a + math.tan(math.radians(shear)) * d
            cx, cy = w/2, h/2
            img = img.transform(
                (w, h), Image.AFFINE,
                (a, b, cx-a*cx-b*cy, d, e, cy-d*cx-e*cy),
                resample=Image.BILINEAR, fillcolor=255)
        except Exception:
            pass
        return img


def main():
    os.makedirs("./weights",    exist_ok=True)
    os.makedirs("./checkpoint", exist_ok=True)

    final_model = "./weights/transformerocr_final.pth"
    if not os.path.exists(final_model):
        print(f" Không tìm thấy {final_model}")
        print("   Chạy train_final.py trước!")
        return

    config = Cfg.load_config_from_file("config_handwriting.yml")
    print(f" Vocab: {len(config['vocab'])} ký tự")

    config['dataset'].update({
        "name":             "hw_viet_finetune",
        "data_root":        "./vietocr_data/",
        "train_annotation": "train_annotation.txt",
        "valid_annotation": "val_annotation.txt",
        "image_height":     32,
        "image_min_width":  32,
        "image_max_width":  640,   # tăng từ 512→640 
    })

    config['optimizer'].update({
        "max_lr":    0.00005,      # thấp — fine-tune nhẹ, không phá model
        "pct_start": 0.1,
    })

    config['trainer'].update({
        "batch_size":  16,
        "iters":       20000,
        "print_every": 100,
        "valid_every": 500,
        "export":      "./weights/transformerocr_company.pth",
        "checkpoint":  "./checkpoint/transformerocr_company_checkpoint.pth",
        "metrics":     500,
        "log":         "./train_company.log",
    })

    config['dataloader'].update({
        "num_workers": 1,
        "pin_memory":  False,
    })

    config['pretrain'] = final_model

    config['device'] = "cuda:0"
    config['aug']    = {"image_aug": True, "masked_language_model": True}

    print("=" * 60)
    print("  Fine-tune với data")
    print("=" * 60)
    print(f"  base model : {final_model}  ← config['pretrain']")
    print(f"  max_lr     : {config['optimizer']['max_lr']}  (thấp — fine-tune nhẹ)")
    print(f"  iters      : {config['trainer']['iters']:,}")
    print(f"  batch_size : {config['trainer']['batch_size']}")
    print(f"  max_width  : {config['dataset']['image_max_width']}")
    print(f"  valid_every: {config['trainer']['valid_every']}")
    print(f"  export     : {config['trainer']['export']}")

    for name, ann in [("train", "./vietocr_data/train_annotation.txt"),
                      ("val",   "./vietocr_data/val_annotation.txt")]:
        if os.path.exists(ann):
            n = sum(1 for _ in open(ann, encoding="utf-8"))
            print(f"  {name:5s}      : {n:,} samples")

    print()
    print("  Mốc theo dõi (tail -f train_company.log):")
    print("    iter 2k → acc_full_seq > 0.35  bình thường")
    print("    iter 5k → acc_full_seq > 0.42  đúng hướng")
    print("    iter 10k→ acc_full_seq > 0.50  mục tiêu")
    print("=" * 60)
    print()

    import shutil
    for d in ["train_hw_viet", "valid_hw_viet",
              "train_hw_viet_finetune", "valid_hw_viet_finetune"]:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"  Xóa cache cũ: {d}/")

    trainer = Trainer(config, pretrained=True, augmentor=HandwritingAugmentor())

    try:
        trainer.train()
    except KeyboardInterrupt:
        print("\n⏸  Đã dừng. Model tốt nhất đã lưu.")

    config.save("config_handwriting_company.yml")
    print(f"\n✅ Xong!")
    print(f"   Model : ./weights/transformerocr_company.pth")
    print(f"   Test  : python Inference_v2.py --dir ./test_images/ "
          f"--model ./weights/transformerocr_company.pth")


if __name__ == "__main__":
    main()