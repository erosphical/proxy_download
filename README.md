# proxy_download

Download high-resolution Magic: The Gathering card images from [Scryfall](https://scryfall.com/) for printing proxies.

Given a decklist-style proxy list, this script fetches each card’s art, optionally compresses it to JPEG sized for Google Docs / PDF printing, and saves images ready to drop into a print layout.

## Features

- Parses common proxy-list formats (quantity, card name, set code, collector number)
- Looks up cards by set/collector number, or by name when no number is given
- Handles special cases (PLST dashed numbers, promo `p` suffixes, foil markers)
- Downloads both faces of double-faced / transform cards as separate files
- Compresses to JPEG by default (smaller PDFs); optional full-res PNG
- Skips cards already present in the output folder
- Respects Scryfall’s rate-limit guidance

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

1. Put your cards in `proxy_list.txt` (one per line):

```text
1 Sol Ring (C21) 263
4 Lightning Bolt (2X2) 117
1x Blitzwing, Cruel Tormentor (BOT)
```

Supported line formats:

- `<qty> <Card Name> (<SET>) <collector_number> [*F*]`
- `<qty>x <Card Name> (<SET>)` — looks up by name within the set

2. Run the script:

```bash
python download_proxies.py
```

Images are written to `output/` as JPEGs sized for a 2.53″ card at 96 DPI (Google Docs default), which keeps print PDFs small.

### Options

```bash
python download_proxies.py [proxy_list] [-o OUTPUT] [--no-compress] [--quality 0-95] [--max-width PX]
```

| Flag | Description |
|------|-------------|
| `proxy_list` | Path to the list file (default: `proxy_list.txt`) |
| `-o`, `--output` | Output folder (default: `output`) |
| `--no-compress` | Keep original Scryfall PNGs instead of JPEG |
| `--quality` | JPEG quality 0–95 (default: 85) |
| `--max-width` | Max image width in pixels before resize (default: 243 ≈ 96 DPI) |

Useful `--max-width` values for a 2.53″ card: `243` (96 DPI), `380` (150 DPI), `506` (200 DPI), `759` (300 DPI).

## Example

```bash
python download_proxies.py my_deck.txt -o proxies --max-width 380
```

## Notes

- Images are for personal proxy printing; respect Scryfall’s [API guidelines](https://scryfall.com/docs/api) and card copyrights.
- Quantity greater than 1 still downloads the image once (you can duplicate files when laying out prints).
- The `*F*` foil marker is ignored for image lookup.
