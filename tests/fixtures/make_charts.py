#!/usr/bin/env python3
"""重新生成 sample_paper.md 引用的测试图表 PNG。

测试 fixture 里的两张图只需要满足一个条件：宽高比不同，
以便覆盖 md_to_latex 的图片宽度启发式（宽图 vs 竖长图）。

    python tests/fixtures/make_charts.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).parent / "charts"

CHARTS = [
    ("fig1_model.png", (900, 380), "#2b6cb0"),   # 宽图 → 铺满
    ("fig2_compare.png", (520, 900), "#c05621"),  # 竖长图 → 收窄
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, size, color in CHARTS:
        im = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(im)
        draw.rectangle([2, 2, size[0] - 3, size[1] - 3], outline=color, width=6)
        draw.rectangle(
            [size[0] // 4, size[1] // 3, size[0] * 3 // 4, size[1] * 2 // 3],
            outline=color,
            width=4,
        )
        im.save(OUT_DIR / name)
        print(f"[OK] {OUT_DIR / name}  {size[0]}x{size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
