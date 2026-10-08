"""Render the app's vector source into a Windows ICO with the desktop extra.

Run ``uv run --no-sync python scripts/generate_icon.py`` after editing the SVG.
Qt's SVG renderer and image encoder suffice; no extra image library is required.
The checked-in ICO makes installer builds independent of regeneration.
"""
from __future__ import annotations

from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[1]
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    source = ROOT / "assets" / "rocket-workbench.svg"
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise RuntimeError(f"Invalid application icon SVG: {source}")
    images = []
    for size in SIZES:
        # Supersampling preserves clean silhouettes at taskbar/favicon sizes.
        canvas = QImage(size * 4, size * 4, QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        renderer.render(painter)
        painter.end()
        canvas = canvas.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not canvas.save(buffer, "PNG"):
            raise RuntimeError(f"Failed to encode {size}px icon")
        images.append(bytes(data))

    offset = 6 + len(SIZES) * 16
    entries = []
    for size, data in zip(SIZES, images, strict=True):
        # Modern Windows ICO entries may use lossless transparent PNG payloads.
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0,
                                   1, 32, len(data), offset))
        offset += len(data)
    target = ROOT / "assets" / "rocket-workbench.ico"
    target.write_bytes(struct.pack("<HHH", 0, 1, len(SIZES)) +
                       b"".join(entries) + b"".join(images))
    public = ROOT / "web" / "public"
    public.mkdir(parents=True, exist_ok=True)
    (public / "icon.svg").write_bytes(source.read_bytes())
    print(f"Wrote {target.relative_to(ROOT)} ({', '.join(map(str, SIZES))} px)")


if __name__ == "__main__":
    main()
