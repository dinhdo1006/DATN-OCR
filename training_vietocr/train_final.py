"""
train_final.py — Train lại từ pretrained, config an toàn cho server chung.

Fix so với các version trước:
  - Dùng config_handwriting.yml (vocab 406 ký tự) thay vì load_config_from_name
  - Bỏ imgaug hoàn toàn (broken với NumPy >= 2.0)
  - Fix augmentor crash (inhomogeneous shape, KeyError)
  - Config an toàn cho server chung (batch=16, num_workers=1, pin_memory=False)
"""
import io, math, os, random, sys, types
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance, ImageOps

# Patch imgaug trước khi import vietocr
for _m in ("imgaug", "imgaug.augmenters", "imgaug.augmenters.meta",
           "imgaug.augmenters.arithmetic", "imgaug.augmenters.blur",
           "imgaug.augmenters.contrast", "imgaug.augmenters.geometric"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)

from vietocr.tool.config import Cfg
from vietocr.model.trainer import Trainer


# ══════════════════════════════════════════════════════════════════════════════
# AUGMENTATION — PIL + NumPy thuần, không dùng imgaug
# ══════════════════════════════════════════════════════════════════════════════

class HandwritingAugmentor:
    def __call__(self, img: Image.Image) -> Image.Image:
        mode = img.mode
        try:
            # 1. Blur
            if random.random() < 0.4:
                img = img.filter(ImageFilter.GaussianBlur(
                    radius=random.uniform(0, 1.5)))

            # 2. Noise
            if random.random() < 0.3:
                arr = np.array(img, dtype=np.float32)
                arr = np.clip(
                    arr + np.random.normal(0, random.uniform(3, 15), arr.shape),
                    0, 255)
                img = Image.fromarray(arr.astype(np.uint8), mode)

            # 3. Brightness
            if random.random() < 0.5:
                img = ImageEnhance.Brightness(img).enhance(
                    random.uniform(0.7, 1.3))

            # 4. Contrast
            if random.random() < 0.4:
                img = ImageEnhance.Contrast(img).enhance(
                    random.uniform(0.7, 1.4))

            # 5. Affine rotate + shear
            if random.random() < 0.5:
                img = self._affine(img,
                                   rotate=random.uniform(-4, 4),
                                   shear=random.uniform(-3, 3))

            # 6. Dilate / Erode — mực đậm / nhạt
            if random.random() < 0.3:
                img = img.filter(
                    ImageFilter.MaxFilter(3) if random.random() < 0.5
                    else ImageFilter.MinFilter(3))

            # 7. Elastic distortion
            if random.random() < 0.25:
                img = self._elastic(img)

            # 8. JPEG artifact
            if random.random() < 0.2:
                img = self._jpeg(img, quality=random.randint(60, 90))

            # Đảm bảo trả về đúng mode gốc
            if img.mode != mode:
                img = img.convert(mode)

        except Exception:
            pass  # Lỗi bất kỳ → trả về ảnh gốc không augment

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
            cx, cy = w / 2, h / 2
            img = img.transform(
                (w, h), Image.AFFINE,
                (a, b, cx - a*cx - b*cy,
                 d, e, cy - d*cx - e*cy),
                resample=Image.BILINEAR, fillcolor=255)
        except Exception:
            pass
        return img

    @staticmethod
    def _elastic(img):
        try:
            arr  = np.array(img, dtype=np.float32)
            h, w = arr.shape[:2]
            r    = max(1, int(0.07 * min(h, w)))

            def _smooth(f):
                # Ép về 2D trước khi GaussianBlur
                t = ((f + 1) * 127.5).clip(0, 255).astype(np.uint8)
                if t.ndim == 3:
                    t = t[:, :, 0]
                return np.array(
                    Image.fromarray(t, mode='L').filter(
                        ImageFilter.GaussianBlur(radius=r)),
                    dtype=np.float32) / 127.5 - 1

            dx = _smooth(np.random.uniform(-1, 1, (h, w)).astype(np.float32) * 1.2)
            dy = _smooth(np.random.uniform(-1, 1, (h, w)).astype(np.float32) * 1.2)
            xi = np.clip(np.arange(w) + dx, 0, w - 1).astype(int)
            yi = np.clip(np.arange(h).reshape(-1, 1) + dy, 0, h - 1).astype(int)
            result = arr[yi, xi] if arr.ndim == 2 else arr[yi, xi, :]
            return Image.fromarray(result.astype(np.uint8), img.mode)
        except Exception:
            return img

    @staticmethod
    def _jpeg(img, quality):
        try:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=quality)
            buf.seek(0)
            out = Image.open(buf).copy()
            buf.close()
            return out.convert(img.mode)
        except Exception:
            return img


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    os.makedirs("./weights",    exist_ok=True)
    os.makedirs("./checkpoint", exist_ok=True)

    # Dùng config_handwriting.yml — vocab 406 ký tự, đầy đủ ký tự tiếng Việt
    # KHÔNG dùng load_config_from_name vì pretrained chỉ có 233 ký tự
    # → KeyError với các ký tự như •, –, ₫ có trong data
    config = Cfg.load_config_from_file("config_handwriting.yml")
    print(f"✅ Vocab: {len(config['vocab'])} ký tự (từ config_handwriting.yml)")

    # ── Dataset ───────────────────────────────────────────────────────────────
    config['dataset'].update({
        "name":             "hw_viet",
        "data_root":        "./vietocr_data/",
        "train_annotation": "train_annotation.txt",
        "valid_annotation": "val_annotation.txt",
        "image_height":     32,
        "image_min_width":  32,
        "image_max_width":  512,
    })

    # ── Optimizer: giữ nguyên như v1 ─────────────────────────────────────────
    config['optimizer'].update({
        "max_lr":    0.0003,
        "pct_start": 0.1,
    })

    # ── Trainer ───────────────────────────────────────────────────────────────
    config['trainer'].update({
        "batch_size":  16,      # giảm từ 32→16: server đang swap 6GB RAM
        "iters":       40000,   # 30k ≈ 21 epochs với 45k data
        "print_every": 200,
        "valid_every": 1000,    # thường hơn v1 (2000) để theo dõi sát
        "export":      "./weights/transformerocr_final.pth",
        "checkpoint":  "./checkpoint/transformerocr_final_checkpoint.pth",
        "metrics":     1000,
        "log":         "./train_final.log",
    })

    # ── Dataloader an toàn server chung ───────────────────────────────────────
    config['dataloader'].update({
        "num_workers": 1,       # ít worker → ít RAM
        "pin_memory":  False,   # không lock RAM
    })

    # Pretrained: dùng vgg_transformer đã tải sẵn nếu có
    config['weights'] = (
        "./weights/vgg_transformer.pth"
        if os.path.exists("./weights/vgg_transformer.pth")
        else "https://vocr.vn/data/vietocr/vgg_transformer.pth"
    )

    config['device'] = "cuda:0"
    config['aug']    = {"image_aug": True, "masked_language_model": True}

    # ── Summary ───────────────────────────────────────────────────────────────
    print("=" * 60)
    print("  VietOCR train_final")
    print("=" * 60)
    print(f"  config     : config_handwriting.yml")
    print(f"  pretrained : {config['weights']}")
    print(f"  vocab      : {len(config['vocab'])} ký tự")
    print(f"  max_lr     : {config['optimizer']['max_lr']}")
    print(f"  iters      : {config['trainer']['iters']:,}")
    print(f"  batch_size : {config['trainer']['batch_size']}")
    print(f"  num_workers: {config['dataloader']['num_workers']}")
    print(f"  pin_memory : {config['dataloader']['pin_memory']}")
    print(f"  valid_every: {config['trainer']['valid_every']}")
    print(f"  export     : {config['trainer']['export']}")
    print(f"  log        : {config['trainer']['log']}")

    for name, ann in [("train", "./vietocr_data/train_annotation.txt"),
                      ("val",   "./vietocr_data/val_annotation.txt")]:
        if os.path.exists(ann):
            n = sum(1 for _ in open(ann, encoding="utf-8"))
            print(f"  {name:5s}      : {n:,} samples")

    print()
    print("  Mốc theo dõi (tail -f train_final.log):")
    print("    iter 10k → acc_full_seq > 0.25")
    print("    iter 20k → acc_full_seq > 0.32")
    print("    iter 30k → acc_full_seq > 0.38  (vượt v1: 0.3457)")
    print("=" * 60)
    print()

    # Xóa cache cũ để tránh conflict với vocab mới
    import shutil
    for d in ["train_hw_viet", "valid_hw_viet"]:
        if os.path.exists(d):
            shutil.rmtree(d)
            print(f"  Xóa cache cũ: {d}/")

    trainer = Trainer(config, pretrained=True, augmentor=HandwritingAugmentor())

    try:
        trainer.train()
    except KeyboardInterrupt:
        print("\n⏸  Đã dừng. Model tốt nhất đã lưu.")

    config.save("config_handwriting_final.yml")
    print(f"\n✅ Xong!")
    print(f"   Model : ./weights/transformerocr_final.pth")
    print(f"   Eval  : python eval.py --model ./weights/transformerocr_final.pth")


if __name__ == "__main__":
    main()