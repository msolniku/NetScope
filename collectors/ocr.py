import re
from pathlib import Path

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

from config.settings import (
    TESSERACT_CMD,
    MAC_CORRECTIONS,
    TX_RATE_CORRECTIONS,
)


# --------------------------------------------------
# Tesseract setup
# --------------------------------------------------

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


# --------------------------------------------------
# Preprocessing parameters
# --------------------------------------------------

UPSCALE_FACTOR   = 2
CONTRAST_FACTOR  = 2.0
THRESHOLD        = 180

TESSERACT_CONFIG = (
    "--psm 6 "
    "-c tessedit_char_whitelist=0123456789abcdefABCDEF:.yesno"
)

EXPECTED_FIELDS = 6

MAC_PATTERN = re.compile(
    r"^[0-9a-fA-F]{2}:"
    r"[0-9a-fA-F]{2}:"
    r"[0-9a-fA-F]{2}:"
    r"[0-9a-fA-F]{2}:"
    r"[0-9a-fA-F]{2}:"
    r"[0-9a-fA-F]{2}$"
)


# --------------------------------------------------
# OCR corrections
# --------------------------------------------------

def correct_mac(mac: str) -> str:
    """Apply known OCR fixes to a MAC string."""
    return MAC_CORRECTIONS.get(mac, mac)


def correct_tx_rate(value: float | None) -> float | None:
    """Apply known OCR fixes to a tx_rate value."""
    if value is None:
        return None
    return TX_RATE_CORRECTIONS.get(value, value)


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def is_valid_mac(mac: str) -> bool:
    return bool(MAC_PATTERN.fullmatch(mac))


def to_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def to_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


# --------------------------------------------------
# Preprocessing
# --------------------------------------------------

def preprocess_image(
    source: Path,
    upscale: int = UPSCALE_FACTOR,
    contrast: float = CONTRAST_FACTOR,
    threshold: int = THRESHOLD,
) -> Image.Image:
    """Load, clean up, and prepare an image for OCR."""
    if not source.exists():
        raise FileNotFoundError(f"Input image not found: {source}")

    image = Image.open(source)
    print(f"Image size: {image.size}")

    image = image.convert("L")
    image = image.resize(
        (image.width * upscale, image.height * upscale),
        Image.Resampling.LANCZOS,
    )
    image = ImageEnhance.Contrast(image).enhance(contrast)
    image = image.filter(ImageFilter.SHARPEN)
    image = image.point(lambda pixel: 255 if pixel > threshold else 0)

    return image


# --------------------------------------------------
# OCR
# --------------------------------------------------

def run_ocr(image: Image.Image, config: str = TESSERACT_CONFIG) -> str:
    return pytesseract.image_to_string(image, config=config)


# --------------------------------------------------
# Parsing
# --------------------------------------------------

def parse_row(line: str) -> dict | None:
    """Parse a single OCR line into a record dict. Returns None if invalid."""
    line = line.strip()
    if not line:
        return None

    if "MAC" in line and "Address" in line:
        return None

    parts = line.split()
    if len(parts) < EXPECTED_FIELDS:
        return None

    mac = parts[0]

    if not is_valid_mac(mac) and len(parts) >= 2:
        possible_mac = parts[0] + parts[1]
        if is_valid_mac(possible_mac):
            mac = possible_mac
            parts.pop(1)

    mac = correct_mac(mac)

    if not is_valid_mac(mac):
        return None

    if len(parts) < EXPECTED_FIELDS:
        return None

    _, tx_packet, rx_packet, tx_rate, power_saving, expired_time = \
        parts[:EXPECTED_FIELDS]

    raw_tx_rate = to_float(tx_rate)

    if raw_tx_rate is not None and raw_tx_rate in TX_RATE_CORRECTIONS:
        print(f"TX_RATE corrected: {raw_tx_rate} -> "
              f"{TX_RATE_CORRECTIONS[raw_tx_rate]}")

    return {
        "mac": mac.lower(),
        "tx_packet": to_int(tx_packet),
        "rx_packet": to_int(rx_packet),
        "tx_rate": correct_tx_rate(raw_tx_rate),
        "power_saving": power_saving.lower(),
        "expired_time": to_int(expired_time),
    }


def parse_records(text: str) -> list[dict]:
    records = []
    for line in text.splitlines():
        record = parse_row(line)
        if record is not None:
            records.append(record)
    return records


# --------------------------------------------------
# Public API
# --------------------------------------------------

def process_image(input_image: Path, upscale: int = UPSCALE_FACTOR) -> list[dict]:
    """Process one image and return structured records."""
    processed_image = input_image.parent / f"{input_image.stem}_processed.png"

    image = preprocess_image(input_image, upscale=upscale)
    image.save(processed_image)
    print(f"Processed image saved: {processed_image}")

    text = run_ocr(image)

    print("\n========== RAW OCR ==========\n")
    print(text)

    records = parse_records(text)

    print("\n========== STRUCTURED DATA ==========\n")
    for r in records:
        print(r)
    print(f"\nDetected users: {len(records)}\n")

    return records