"""Pack the rendered PNGs into a single Windows .ico.

    py scripts\\build_icon.py

An authoring step, not something the app runs. The PNGs themselves come from
scripts/make_icon.ps1, which crops them out of the source artwork using
Windows' own imaging — so neither step adds a dependency to the program.

Since Vista an .ico may hold PNG data directly, which means packing one needs
nothing but a struct and a file header.
"""

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SIZES = (256, 128, 64, 48, 32, 16)

ICONDIR = "<HHH"        # reserved, type (1 = icon), image count
ICONDIRENTRY = "<BBBBHHII"  # w, h, colours, reserved, planes, bpp, bytes, offset


def build(sizes=SIZES, destination=None):
    destination = destination or ASSETS / "icon.ico"

    images = []
    for size in sizes:
        source = ASSETS / f"icon-{size}.png"
        if not source.exists():
            print(f"missing {source.name} — run scripts/make_icon.ps1 first")
            return 1
        images.append((size, source.read_bytes()))

    header = struct.pack(ICONDIR, 0, 1, len(images))
    offset = len(header) + len(images) * struct.calcsize(ICONDIRENTRY)

    entries, payload = [], []
    for size, data in images:
        entries.append(struct.pack(
            ICONDIRENTRY,
            # 0 means 256 in the directory; the byte cannot hold 256 itself.
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0, 0, 1, 32, len(data), offset,
        ))
        payload.append(data)
        offset += len(data)

    destination.write_bytes(header + b"".join(entries) + b"".join(payload))
    print(f"{destination.name}  {destination.stat().st_size // 1024} KB, "
          f"{len(images)} sizes: {', '.join(str(s) for s in sizes)}")
    return 0


if __name__ == "__main__":
    sys.exit(build())
