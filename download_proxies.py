#!/usr/bin/env python3
"""
Download high-res Magic: The Gathering card images from Scryfall.

Input format (one card per line):
  <qty> <Card Name> (<SET>) <collector_number> [*F*]

Special cases handled:
  - PLST set with dashed collector numbers: (PLST) MRD-159
  - Promo collector numbers with 'p' suffix: (PWAR) 50p
  - Foil indicator '*F*' is ignored for image lookup
  - Quantity > 1 still downloads the image once
  - Double-faced / transform cards download both faces as separate files named
    after each face (e.g. "Blitzwing, Cruel Tormentor (BOT) 4.jpg" and
    "Blitzwing, Adaptive Assailant (BOT) 4.jpg")

Images are saved as JPEG by default to keep PDF sizes manageable when
printing (100 cards as PNG ≈ 100 MB+; as JPEG at 150 DPI / 85% quality ≈ 5–8 MB).
Use --no-compress to keep the original PNG.
"""

import re
import sys
import time
import argparse
from pathlib import Path

import requests
from PIL import Image

SCRYFALL_CARD_URL = "https://api.scryfall.com/cards/{set}/{number}"
SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"
REQUEST_DELAY = 0.1  # Scryfall asks for >= 50-100ms between requests
# Scryfall rejects requests without User-Agent and Accept (HTTP 400).
HTTP_HEADERS = {
    "User-Agent": "proxy_download/1.0",
    "Accept": "application/json;q=0.9,*/*;q=0.8",
}

# MTG card width: 2.53"
#   300 DPI → 759 px  (Scryfall PNG original)
#   200 DPI → 506 px
#   150 DPI → 380 px
#    96 DPI → 243 px  ← default (Google Docs / most PDF viewers assume 96 DPI when
#                        DPI metadata is absent or ignored, so this renders at exactly
#                        2.53" wide without any manual resize step)
CARD_WIDTH_INCHES = 2.53
GOOGLE_DOCS_DPI = 96
DEFAULT_MAX_WIDTH = round(CARD_WIDTH_INCHES * GOOGLE_DOCS_DPI)  # 243 px
DEFAULT_JPEG_QUALITY = 85  # 0–95; 85 is a good quality/size balance

LINE_PATTERN = re.compile(
    r"^\s*\d+\s+(.+?)\s+\((\w+)\)\s+([\w-]+)(?:\s+\*F\*)?\s*$"
)
# Format: "1x Card Name (SET)" — no collector number; looked up by name
LINE_PATTERN_X = re.compile(
    r"^\s*\d+x\s+(.+?)\s+\((\w+)\)\s*$"
)


def parse_proxy_list(path: Path) -> list[dict]:
    cards = []
    seen = set()

    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue

            m = LINE_PATTERN.match(line)
            if m:
                name, set_code, collector_number = m.group(1), m.group(2), m.group(3)
                key = (set_code.lower(), collector_number.lower())
                if key in seen:
                    continue
                seen.add(key)
                cards.append(
                    {
                        "name": name,
                        "set": set_code.lower(),
                        "number": collector_number,
                        "line": lineno,
                    }
                )
                continue

            mx = LINE_PATTERN_X.match(line)
            if mx:
                name, set_code = mx.group(1), mx.group(2)
                key = (set_code.lower(), name.lower())
                if key in seen:
                    continue
                seen.add(key)
                cards.append(
                    {
                        "name": name,
                        "set": set_code.lower(),
                        "number": None,  # will use named lookup
                        "line": lineno,
                    }
                )
                continue

            print(f"  [WARN] Line {lineno} skipped (unrecognised format): {line!r}")

    return cards


def safe_filename(name: str, set_code: str, number: str | None, ext: str = "jpg") -> str:
    safe_name = re.sub(r'[<>:"/\\|?*]', "", name).strip()
    if number is not None:
        return f"{safe_name} ({set_code.upper()}) {number}.{ext}"
    return f"{safe_name} ({set_code.upper()}).{ext}"


def compress_image(src: Path, max_width: int, quality: int) -> None:
    """Re-save *src* as a JPEG, resizing to *max_width* if larger, then replace the file.

    DPI metadata is embedded so PDF viewers / macOS Preview render the image at
    the correct physical size (CARD_WIDTH_INCHES wide) rather than guessing.
    """
    with Image.open(src) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        dpi = round(img.width / CARD_WIDTH_INCHES)
        jpeg_path = src.with_suffix(".jpg")
        img.save(jpeg_path, "JPEG", quality=quality, optimize=True, dpi=(dpi, dpi))
    if src.suffix.lower() != ".jpg":
        src.unlink()


def fetch_card_image_urls(set_code: str, number: str | None, name: str = "") -> list[tuple[str | None, str]]:
    """Return a list of (face_name_or_None, image_url) for the card.

    Single-faced cards return one entry with face_name=None (caller uses card name).
    Double/multi-faced cards return one entry per face with the face's own name.
    When *number* is None, fall back to a named lookup using *name* + *set_code*.
    """
    if number is None:
        url = SCRYFALL_NAMED_URL
        params = {"exact": name, "set": set_code}
        try:
            resp = requests.get(url, headers=HTTP_HEADERS, params=params, timeout=15)
            resp.raise_for_status()
        except requests.HTTPError as e:
            print(f"    [ERROR] HTTP {e.response.status_code} from Scryfall named lookup: {name!r} ({set_code.upper()})")
            return []
        except requests.RequestException as e:
            print(f"    [ERROR] Request failed: {e}")
            return []
    else:
        url = SCRYFALL_CARD_URL.format(set=set_code, number=number)
        try:
            resp = requests.get(url, headers=HTTP_HEADERS, timeout=15)
            resp.raise_for_status()
        except requests.HTTPError as e:
            print(f"    [ERROR] HTTP {e.response.status_code} from Scryfall: {url}")
            return []
        except requests.RequestException as e:
            print(f"    [ERROR] Request failed: {e}")
            return []

    data = resp.json()

    # Single-faced cards
    if "image_uris" in data:
        img_url = data["image_uris"].get("png") or data["image_uris"].get("large")
        if img_url:
            return [(None, img_url)]
        print(f"    [WARN] No image_uris found in card data for {set_code}/{number}")
        return []

    # Double-faced / multi-faced cards — download every face
    faces = data.get("card_faces", [])
    results = []
    for face in faces:
        if "image_uris" not in face:
            continue
        img_url = face["image_uris"].get("png") or face["image_uris"].get("large")
        if img_url:
            results.append((face.get("name"), img_url))
    if not results:
        print(f"    [WARN] No image_uris found in card data for {set_code}/{number}")
    return results


def download_image(image_url: str, dest: Path) -> bool:
    try:
        resp = requests.get(image_url, headers=HTTP_HEADERS, timeout=30, stream=True)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    [ERROR] Failed to download image: {e}")
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Download high-res Magic card images from Scryfall.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "proxy_list",
        nargs="?",
        default="proxy_list.txt",
        help="Path to the proxy list file",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output",
        help="Output folder for downloaded images",
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Keep original PNG files instead of converting to JPEG",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_JPEG_QUALITY,
        metavar="0-95",
        help="JPEG quality (ignored with --no-compress)",
    )
    parser.add_argument(
        "--max-width",
        type=int,
        default=DEFAULT_MAX_WIDTH,
        metavar="PX",
        help=(
            "Resize images wider than this many pixels (ignored with --no-compress). "
            "243 px = 96 DPI (Google Docs default), 380 px = 150 DPI, "
            "506 px = 200 DPI, 759 px = 300 DPI — all for a 2.53\" card."
        ),
    )
    args = parser.parse_args()

    proxy_path = Path(args.proxy_list)
    if not proxy_path.exists():
        print(f"Error: proxy list not found: {proxy_path}")
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    compress = not args.no_compress
    if compress:
        print(
            f"Compression: JPEG quality={args.quality}, max-width={args.max_width}px "
            f"(use --no-compress to keep original PNGs)\n"
        )
    else:
        print("Compression: disabled — saving original PNGs\n")

    print(f"Parsing {proxy_path} ...")
    cards = parse_proxy_list(proxy_path)
    print(f"Found {len(cards)} unique card printing(s) to download.\n")

    success, skipped, failed = 0, 0, 0

    for i, card in enumerate(cards, 1):
        print(f"[{i}/{len(cards)}] {card['name']} ({card['set'].upper()}) {card['number']}")

        faces = fetch_card_image_urls(card["set"], card["number"], card["name"])
        time.sleep(REQUEST_DELAY)

        if not faces:
            failed += 1
            continue

        for face_name, image_url in faces:
            display_name = face_name if face_name else card["name"]
            ext = "jpg" if compress else "png"
            filename = safe_filename(display_name, card["set"], card["number"], ext)
            dest = output_dir / filename

            if dest.exists():
                print(f"    Already downloaded: {filename}")
                skipped += 1
                continue

            if len(faces) > 1:
                print(f"    Face: {display_name}")

            # Always download to a temp PNG first, then compress in-place if requested
            png_dest = dest.with_suffix(".png")
            ok = download_image(image_url, png_dest)
            if ok:
                if compress:
                    try:
                        compress_image(png_dest, args.max_width, args.quality)
                        final = dest  # .jpg
                    except Exception as e:
                        print(f"    [WARN] Compression failed ({e}), keeping PNG")
                        final = png_dest
                else:
                    final = png_dest
                size_kb = final.stat().st_size // 1024
                print(f"    Saved: {final.name} ({size_kb} KB)")
                success += 1
            else:
                failed += 1

            time.sleep(REQUEST_DELAY)

    print(f"\nDone. {success} downloaded, {skipped} skipped, {failed} failed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
