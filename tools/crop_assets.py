"""Crop sprite assets from the design sheet into webapp/assets/.

Source: /Users/madside/Downloads/image-Photoroom.png (RGBA, 1536x1024).
Every rough box is trimmed to its alpha bounding box, so boxes only need
to fully contain the sprite and not touch its neighbours.
Usage: ./venv/bin/python tools/crop_assets.py [--sheet]
  --sheet also writes /tmp/assets_sheet.png contact sheet for review.
"""
import pathlib
import sys
from PIL import Image

SRC = pathlib.Path('/Users/madside/Downloads/image-Photoroom.png')
OUT = pathlib.Path(__file__).resolve().parent.parent / 'webapp' / 'assets'

# name -> rough (x1, y1, x2, y2)
BOXES = {
    'room':    (14, 4, 602, 502),
    'pet':     (628, 178, 872, 478),
    'avatar':  (652, 12, 798, 158),
    'apple':   (843, 513, 912, 600),
    'fish':    (918, 513, 992, 600),
    'cake':    (998, 510, 1068, 600),
    'yarn':    (1074, 510, 1152, 600),
    'coin':    (843, 606, 908, 680),
    'bolt':    (918, 606, 988, 680),
    'heart':   (998, 606, 1068, 680),
    'star':    (1076, 606, 1142, 680),
    'gem':     (1148, 606, 1218, 680),
    'potion':  (843, 692, 908, 786),
    'bow':     (916, 692, 988, 786),
    'crown':   (996, 686, 1078, 790),
    'hat':     (1032, 686, 1120, 794),
    'scarf':   (1102, 686, 1180, 794),
    'face_0':  (1198, 510, 1310, 618),
    'face_1':  (1296, 510, 1408, 618),
    'face_2':  (1392, 505, 1508, 618),
    'face_3':  (1198, 606, 1310, 716),
    'face_4':  (1296, 606, 1408, 716),
    'face_5':  (1392, 606, 1508, 716),
    'face_6':  (1198, 706, 1310, 818),
    'face_7':  (1296, 706, 1408, 818),
    'face_8':  (1392, 706, 1508, 818),
    'heart_full':  (930, 922, 992, 990),
    'heart_empty': (996, 922, 1058, 990),
    'star_big':    (1130, 922, 1200, 998),
    'paw_big':     (1196, 928, 1262, 1000),
}

# sprites that may have grabbed a piece of a neighbour: keep only the
# largest connected alpha blob. Multi-part art (room, pet+ball, faces with
# detached tears) must NOT be filtered.
LARGEST_BLOB = {'star', 'gem', 'crown', 'hat', 'scarf', 'bow'}


def keep_largest_blob(img: Image.Image) -> Image.Image:
    """Drop everything except the biggest 4-connected alpha component."""
    w, h = img.size
    mask = img.getchannel('A').point(lambda a: 255 if a > 10 else 0)
    px = mask.load()
    seen = bytearray(w * h)
    best, best_size = None, 0
    for start in range(w * h):
        if seen[start] or not px[start % w, start // w]:
            continue
        stack = [start]
        seen[start] = 1
        comp = []
        while stack:
            idx = stack.pop()
            comp.append(idx)
            x, y = idx % w, idx // w
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    nidx = ny * w + nx
                    if not seen[nidx] and px[nx, ny]:
                        seen[nidx] = 1
                        stack.append(nidx)
        if len(comp) > best_size:
            best_size, best = len(comp), comp
    out = Image.new('RGBA', img.size, (0, 0, 0, 0))
    if best:
        opaque = img.load()
        out_px = out.load()
        for idx in best:
            x, y = idx % w, idx // w
            out_px[x, y] = opaque[x, y]
    return out


def crop_all(sheet: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    im = Image.open(SRC).convert('RGBA')
    crops = {}
    for name, (x1, y1, x2, y2) in BOXES.items():
        cell = im.crop((x1, y1, x2, y2))
        bbox = cell.getchannel('A').getbbox()
        if bbox is None:
            print('EMPTY:', name)
            continue
        cell = cell.crop(bbox)
        if name in LARGEST_BLOB:
            cell = keep_largest_blob(cell)
        pad = 2
        bbox = cell.getchannel('A').getbbox()
        bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad),
                min(cell.width, bbox[2] + pad), min(cell.height, bbox[3] + pad))
        sprite = cell.crop(bbox)
        sprite.save(OUT / ('%s.png' % name))
        crops[name] = sprite
        print('%-12s %dx%d' % (name, sprite.width, sprite.height))
    if sheet:
        cols = 6
        cell_w = max(s.width for s in crops.values()) + 16
        cell_h = max(s.height for s in crops.values()) + 16
        rows = (len(crops) + cols - 1) // cols
        board = Image.new('RGBA', (cols * cell_w, rows * cell_h), (40, 40, 60, 255))
        for i, (name, s) in enumerate(crops.items()):
            x = (i % cols) * cell_w + 8
            y = (i // cols) * cell_h + 8
            board.alpha_composite(s, (x, y))
        board.save('/tmp/assets_sheet.png')
        print('sheet -> /tmp/assets_sheet.png')


if __name__ == '__main__':
    crop_all('--sheet' in sys.argv)
