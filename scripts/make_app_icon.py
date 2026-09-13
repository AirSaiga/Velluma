# SPDX-License-Identifier: AGPL-3.0-only
"""应用图标占位图生成器。

⚠ 换图标不需要跑本脚本：唯一图标源是 frontend/electron/app-icon.png，
拿任意方形 PNG（≥256×256，推荐 512+）覆盖它即可——开发窗口/任务栏随应用重启生效，
打包 exe 图标由 electron-builder 在 build.win.icon 处自动转 ico。
本脚本只负责重新生成出厂占位图（深墨底 + 羊皮纸 V 字 + 金墨笔触）。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 2048  # 超采样画布，最后缩到 512 保证边缘平滑
OUT = Path(__file__).resolve().parents[1] / "frontend" / "electron" / "app-icon.png"
BG = (35, 40, 56, 255)        # 深墨蓝
FG = (237, 228, 206, 255)     # 羊皮纸
ACCENT = (200, 169, 106, 255)  # 金墨


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("georgiab.ttf", "timesbd.ttf", "arialbd.ttf"):
        p = Path("C:/Windows/Fonts") / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=int(SIZE * 0.22), fill=BG)
    font = _load_font(int(SIZE * 0.62))
    bbox = d.textbbox((0, 0), "V", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (SIZE - w) / 2 - bbox[0]
    y = (SIZE - h) / 2 - bbox[1] - SIZE * 0.03
    d.text((x, y), "V", font=font, fill=FG)
    ly = y + bbox[3] + SIZE * 0.05
    d.rounded_rectangle(
        [SIZE * 0.32, ly, SIZE * 0.68, ly + SIZE * 0.016],
        radius=SIZE * 0.008,
        fill=ACCENT,
    )
    img = img.resize((512, 512), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
