"""Makes WrathUnleashedUI's own art (Interface/AddOns/WrathUnleashedUI/Media) from the website's Leyline art:
the Leyline mark (the crystal in its swirl, stream/www-files/art/leyline-swirl-512.png + leyline-crystal-512.png)
at 64x64 and 128x128, and an 8x8 white square for backdrops. 32-bit uncompressed TGA, power-of-two sizes, as the
3.3.5a client reads them. Our own art only: no game files.

    python3 -I stream/fui-web/make-wuui-media.py        (from the repo root; needs Pillow)
"""
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ART = os.path.join(ROOT, "stream", "www-files", "art")
OUT = os.path.join(ROOT, "stream", "fui-web", "Interface", "AddOns", "WrathUnleashedUI", "Media")


def mark():
    swirl = Image.open(os.path.join(ART, "leyline-swirl-512.png")).convert("RGBA").resize((512, 512), Image.LANCZOS)
    crystal = Image.open(os.path.join(ART, "leyline-crystal-512.png")).convert("RGBA")
    crystal = crystal.crop(crystal.getbbox())
    h = int(512 * 0.42)
    w = int(crystal.width * h / crystal.height)
    crystal = crystal.resize((w, h), Image.LANCZOS)
    out = swirl.copy()
    out.alpha_composite(crystal, ((512 - w) // 2, (512 - h) // 2))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    m = mark()
    for size in (64, 128):
        m.resize((size, size), Image.LANCZOS).save(os.path.join(OUT, f"leyline-mark-{size}.tga"), compression=None)
    Image.new("RGBA", (8, 8), (255, 255, 255, 255)).save(os.path.join(OUT, "white8x8.tga"), compression=None)
    print("wrote", ", ".join(sorted(os.listdir(OUT))))


if __name__ == "__main__":
    sys.exit(main())
