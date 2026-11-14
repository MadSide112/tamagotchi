#!/usr/bin/env python3
"""Квантование PNG-ассетов мини-аппа в палитровый формат (PNG8).

Пиксель-арт имеет мало уникальных цветов, поэтому палитровое PNG весит
в разы меньше truecolor-PNG без видимой потери качества. Запуск:
    ./venv/bin/python tools/optimize_assets.py [каталог]
По умолчанию обрабатывает webapp/assets. Файлы перезаписываются на месте.
"""
import sys
from pathlib import Path

from PIL import Image

MAX_COLORS = 128


def optimize(path: Path) -> None:
    img = Image.open(path)
    before = path.stat().st_size
    if img.mode in ('P', '1'):
        print(f'{path.name}: уже палитровый ({before} B), пропуск')
        return
    # FASTOCTREE — единственный метод, корректно работающий с RGBA
    pal = img.quantize(colors=MAX_COLORS, method=Image.FASTOCTREE,
                       dither=Image.Dither.NONE)
    pal.save(path, optimize=True)
    after = path.stat().st_size
    print(f'{path.name}: {before} -> {after} B (-{100 - after * 100 // before}%)')


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('webapp/assets')
    files = sorted(root.glob('*.png'))
    if not files:
        print(f'нет PNG в {root}')
        return
    total_before = total_after = 0
    for f in files:
        optimize(f)
    for f in files:
        total_before += f.stat().st_size
    print(f'итого по {len(files)} файлам: {total_before} B')


if __name__ == '__main__':
    main()
