#!/usr/bin/env python3
"""finalize.py RAW NAME [cutout args...]: full-res PNG in final/png/, 900px WebP in final/ for the boards."""
import subprocess
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
raw, name, extra = sys.argv[1], sys.argv[2], sys.argv[3:]
png = HERE / "final" / "png" / f"{name}.png"
png.parent.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, str(HERE / "cutout.py"), raw, str(png), "--max-h", "1400", *extra], check=True,
               stdout=subprocess.DEVNULL)
im = Image.open(png)
if im.height > 900:
    im = im.resize((round(im.width * 900 / im.height), 900), Image.LANCZOS)
webp = HERE / "final" / f"{name}.webp"
im.save(webp, "WEBP", quality=86, method=6)
print(f"{name}: png {Image.open(png).size} {png.stat().st_size // 1024}K, webp {im.size} {webp.stat().st_size // 1024}K")
