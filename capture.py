"""Screenshot capture + OCR + color-based enchant detection (ТЗ §6-8)."""
import os
import re

import cv2
import mss
import numpy as np
import pytesseract
from PIL import Image

import storage
from config_io import load_aliases, load_config, load_enchant_colors, load_zones, zones_configured
from paths import path_in_base

DEBUG_DIR = path_in_base("debug")

ALIAS_RE = re.compile(r"\(([^)]+)\)")


def grab_zone(sct: "mss.mss", zone: dict) -> np.ndarray:
    bbox = {
        "left": int(zone["x"]),
        "top": int(zone["y"]),
        "width": int(zone["w"]),
        "height": int(zone["h"]),
    }
    shot = sct.grab(bbox)
    img_bgra = np.array(shot)
    return cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2BGR)


def preprocess_text(img_bgr: np.ndarray, scale: int = 3) -> np.ndarray:
    """grayscale -> binarize (Otsu) -> upscale, per ТЗ §8.3."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def _run_ocr(img_bgr: np.ndarray, tesseract_cmd: str, tess_config: str) -> str:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    processed = preprocess_text(img_bgr)
    pil_img = Image.fromarray(processed)
    text = pytesseract.image_to_string(pil_img, config=tess_config)
    return text.strip()


def ocr_item_name(img_bgr: np.ndarray, tesseract_cmd: str) -> str:
    return _run_ocr(img_bgr, tesseract_cmd, "--psm 7 -l rus+eng")


def ocr_price(img_bgr: np.ndarray, tesseract_cmd: str) -> str:
    return _run_ocr(
        img_bgr, tesseract_cmd,
        "--psm 7 -c tessedit_char_whitelist=0123456789,",
    )


def parse_item_name(raw: str):
    """'Мантия друида (знаток)' -> ('Мантия друида', 'знаток')."""
    raw = raw.strip()
    match = ALIAS_RE.search(raw)
    if not match:
        return raw, None
    alias = match.group(1).strip().lower()
    base_name = raw[: match.start()].strip()
    return base_name, alias


def resolve_tier(alias, aliases: dict):
    if not alias:
        return None
    return aliases.get(alias.lower())


def parse_price(raw: str, thousands_sep: str):
    if not raw:
        return None
    cleaned = raw.replace(thousands_sep, "")
    cleaned = re.sub(r"[^0-9]", "", cleaned)
    if not cleaned:
        return None
    value = int(cleaned)
    if value <= 0 or len(cleaned) > 9:
        return None
    return value


def dominant_hsv(img_bgr: np.ndarray, bin_size: int = 4):
    """Mean HSV over the most common hue bucket in the image, rather than
    a flat mean over all pixels. The enchant color bar isn't perfectly flat
    (bevel/shading), so a plain per-pixel mean lands between the two real
    shades; bucketing hue and keeping only the largest cluster reflects the
    bar's actual color instead."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0].flatten(), hsv[:, :, 1].flatten(), hsv[:, :, 2].flatten()
    bins = (h // bin_size).astype(int)
    vals, counts = np.unique(bins, return_counts=True)
    dominant_bin = vals[np.argmax(counts)]
    mask = bins == dominant_bin
    return float(h[mask].mean()), float(s[mask].mean()), float(v[mask].mean())


def detect_enchant_debug(img_bgr: np.ndarray, enchant_colors: dict):
    """The item_enchant zone is a solid color bar under the item icon
    whose color encodes the enchant level (calibrated from real captures,
    not a guess — see enchant_colors.json). The zone's dominant color is
    matched to the nearest reference color in HSV space.

    Returns (level, debug) where debug carries the sampled color and the
    distance to the chosen reference, for calibration/troubleshooting."""
    h, s, v = dominant_hsv(img_bgr)
    best_level, best_dist = None, None
    for level_str, ref in enchant_colors.items():
        try:
            level = int(level_str)
        except ValueError:
            continue
        dh = min(abs(h - ref["h"]), 180 - abs(h - ref["h"]))
        ds = s - ref.get("s", 0)
        dv = v - ref.get("v", 0)
        dist = (dh ** 2 + ds ** 2 + dv ** 2) ** 0.5
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_level = level
    debug = {"h": h, "s": s, "v": v, "matched_level": best_level, "distance": best_dist}
    return best_level, debug


def detect_enchant(img_bgr: np.ndarray, enchant_colors: dict):
    level, _ = detect_enchant_debug(img_bgr, enchant_colors)
    return level


def save_enchant_debug(img_bgr: np.ndarray, debug: dict, level) -> None:
    """Dump the exact captured item_enchant zone + the sampled color to
    disk (overwriting the previous ones) so they can be shared to tune
    enchant_colors.json against a real, live capture."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        upscale = 8
        big = cv2.resize(img_bgr, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_NEAREST)
        # cv2.imwrite silently fails on Windows paths containing non-ASCII
        # characters (e.g. Cyrillic folder names) — encode in memory and
        # write with plain Python I/O instead, which handles Unicode paths.
        ok, buf = cv2.imencode(".png", big)
        if ok:
            with open(os.path.join(DEBUG_DIR, "last_enchant.png"), "wb") as f:
                f.write(buf.tobytes())

        lines = [
            f"detected level: {level}",
            f"sampled color: H={debug['h']:.1f} S={debug['s']:.1f} V={debug['v']:.1f}",
            f"distance to matched reference: {debug['distance']:.1f}",
        ]
        with open(os.path.join(DEBUG_DIR, "last_enchant.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass  # debug dump must never break a real capture


def do_capture(item_class: str) -> dict:
    """One F8 capture cycle (ТЗ §8). Returns a result dict; never raises
    for expected failure modes (missing zones/class), only for hard
    errors (e.g. tesseract not installed), which the caller should catch."""
    zones = load_zones()
    if not zones_configured(zones):
        return {"ok": False, "reason": "zones_not_configured"}
    if not item_class:
        return {"ok": False, "reason": "class_not_selected"}

    config = load_config()
    aliases = load_aliases()

    with mss.mss() as sct:
        name_img = grab_zone(sct, zones["item_name"])
        price_img = grab_zone(sct, zones["sell_price"])
        enchant_img = grab_zone(sct, zones["item_enchant"])

    raw_name = ocr_item_name(name_img, config["tesseract_path"])
    raw_price = ocr_price(price_img, config["tesseract_path"])

    base_name, alias = parse_item_name(raw_name)
    if not base_name:
        return {"ok": False, "reason": "empty_name", "raw_name": raw_name}

    tier = resolve_tier(alias, aliases)
    price = parse_price(raw_price, config["price_thousands_separator"])
    enchant_colors = load_enchant_colors()
    enchant, enchant_debug = detect_enchant_debug(enchant_img, enchant_colors)
    save_enchant_debug(enchant_img, enchant_debug, enchant)
    needs_review = tier is None or price is None

    db_path = storage.resolve_db_path(config["db_path"])
    storage.init_db(db_path)
    storage.upsert_item(
        db_path=db_path,
        item_class=item_class,
        item_name=base_name,
        tier=tier,
        enchant=enchant if enchant is not None else 0,
        price=price,
        needs_review=needs_review,
    )

    return {
        "ok": True,
        "item_name": base_name,
        "alias": alias,
        "tier": tier,
        "enchant": enchant,
        "enchant_debug": enchant_debug,
        "price": price,
        "needs_review": needs_review,
    }
