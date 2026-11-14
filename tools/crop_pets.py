"""Cut pet species sprites out of source sheets into webapp/assets/.

Input: a 3x2 grid sheet (dog, bunny, hamster / fox, duck, panda) and a
single snow leopard image, both RGBA with transparent background.
Output: one pet_<id>.png per species, 223x278, sprite bottom-aligned and
centered — the same layout as the existing pet.png, so the CSS positions
each look identically inside the room.
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'webapp' / 'assets'
OUT_SIZE = (223, 278)  # must match pet.png

GRID_SRC = '/Users/madside/Downloads/image_552a901d-Photoroom.png'
LEO_SRC = '/Users/madside/Downloads/image_683737ab-Photoroom.png'

# (output id, column, row) on the 3x2 grid sheet
GRID_MAP = [
    ('pet_dog', 0, 0),
    ('pet_bunny', 1, 0),
    ('pet_hamster', 2, 0),
    ('pet_fox', 0, 1),
    ('pet_duck', 1, 1),
    ('pet_panda', 2, 1),
]


def fit_bottom_center(sprite: Image.Image, size: tuple) -> Image.Image:
    """Scale sprite to fit inside size (LANCZOS), paste bottom-center."""
    canvas = Image.new('RGBA', size, (0, 0, 0, 0))
    bbox = sprite.getbbox()
    if bbox:
        sprite = sprite.crop(bbox)
    sprite.thumbnail(size, Image.LANCZOS)
    x = (size[0] - sprite.width) // 2
    y = size[1] - sprite.height
    canvas.paste(sprite, (x, y), sprite)
    return canvas


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    sheet = Image.open(GRID_SRC).convert('RGBA')
    cell_w = sheet.width / 3.0
    cell_h = sheet.height / 2.0
    for out_id, col, row in GRID_MAP:
        left = int(round(col * cell_w))
        top = int(round(row * cell_h))
        cell = sheet.crop((left, top, left + int(round(cell_w)),
                           top + int(round(cell_h))))
        fit_bottom_center(cell, OUT_SIZE).save(ASSETS / (out_id + '.png'))
        print('ok', out_id)

    leo = Image.open(LEO_SRC).convert('RGBA')
    fit_bottom_center(leo, OUT_SIZE).save(ASSETS / 'pet_snow_leopard.png')
    print('ok pet_snow_leopard')


if __name__ == '__main__':
    main()
