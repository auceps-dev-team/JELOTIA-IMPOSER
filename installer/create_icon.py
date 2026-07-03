"""
Génère l'icône jelotia.ico pour l'installeur et l'application.
Usage : python installer/create_icon.py
Requiert : Pillow (pip install Pillow)
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


SIZES = [16, 32,48, 64, 128, 256]
OUTPUT = Path(__file__).parent / "jelotia.ico"


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background: rounded square with orange gradient approximation
    padding = max(2, size // 16)
    bg_box = [padding, padding, size - padding, size - padding]
    draw.rounded_rectangle(bg_box, radius=size // 6, fill=(217, 122, 39, 255))

    # Inner accent bar (simulates printing press)
    bar_h = size // 8
    bar_y = size // 2 - bar_h // 2
    draw.rectangle(
        [padding * 3, bar_y, size - padding * 3, bar_y + bar_h],
        fill=(255, 255, 255, 200),
    )

    # Letter "J" centred
    text = "J"
    font_size = max(8, size // 2)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except (IOError, OSError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1]
    draw.text((tx, ty), text, font=font, fill=(255, 255, 255, 255))

    return img


def main():
    frames = [draw_icon(s) for s in SIZES]
    frames[0].save(
        OUTPUT,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=frames[1:],
    )
    print(f"Icone générée : {OUTPUT}")


if __name__ == "__main__":
    main()
