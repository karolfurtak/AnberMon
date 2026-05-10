#!/bin/bash
# AnberMon installer dla Anbernic RG40XX V
# Uruchom z root (lub sudo) na konsoli — przez SSH lub terminal
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APPS_DIR="/mnt/mmc/Roms/APPS"
APP_DIR="$APPS_DIR/anbermon"
IMGS_DIR="$APPS_DIR/Imgs"

echo "=== AnberMon install ==="

# 1. SDL2 app
mkdir -p "$APP_DIR"
cp "$REPO_DIR/app/main.py" "$APP_DIR/main.py"
cp "$REPO_DIR/app/AnberMon.sh" "$APPS_DIR/AnberMon.sh"
chmod +x "$APPS_DIR/AnberMon.sh"
echo "✓ App skopiowane do $APP_DIR"

# 2. Ikona (oscyloskop generowany w PIL)
mkdir -p "$IMGS_DIR"
python3 - <<EOF
from PIL import Image, ImageDraw
import math
img = Image.new('RGBA', (240, 180), (0,0,0,0))
d = ImageDraw.Draw(img)
d.rectangle([(0,0),(240,180)], fill=(15,20,35,255))
# siatka
for x in range(20, 240, 20):
    d.line([(x, 30), (x, 150)], fill=(40,55,80,255))
for y in range(40, 160, 20):
    d.line([(20, y), (220, y)], fill=(40,55,80,255))
# ramka oscyloskopu
d.rectangle([(20, 30), (220, 150)], outline=(80,180,255,255), width=2)
# sinusoida
pts = []
for x in range(20, 220):
    y = 90 + int(math.sin((x-20) * 0.08) * 40)
    pts.append((x, y))
d.line(pts, fill=(80,220,100,255), width=2)
img.save('$IMGS_DIR/AnberMon.png')
EOF
echo "✓ Ikona w $IMGS_DIR/AnberMon.png"

# 3. Sprawdź zależności
python3 -c "import sdl2" 2>/dev/null || echo "⚠️  brak pysdl2 — pip install pysdl2"
python3 -c "import evdev" 2>/dev/null || echo "⚠️  brak evdev — pip install evdev"
python3 -c "import PIL" 2>/dev/null || echo "⚠️  brak Pillow — pip install Pillow"
python3 -c "import psutil" 2>/dev/null || echo "⚠️  brak psutil — pip install psutil"

echo ""
echo "Zainstalowane. Uruchom 'AnberMon' z App Center."
