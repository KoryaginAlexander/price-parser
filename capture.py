"""Screenshot capture + OCR + pip-based enchant detection (ТЗ §6-8)."""
import os
import re

import cv2
import mss
import numpy as np
import pytesseract
from PIL import Image

import storage
from config_io import load_aliases, load_config, load_zones, zones_configured
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


def detect_enchant_debug(img_bgr: np.ndarray, s_threshold: float, v_threshold: float,
                          max_pips: int = 4):
    """The item_enchant zone is the row of up to `max_pips` diamond pips
    under the item icon (ТЗ §7, Variant B): filled pips are a saturated
    color (green/purple/etc.), empty ones are dark grey.

    Rather than slicing the zone into `max_pips` fixed-width columns (which
    breaks if the marked zone isn't pixel-perfect), this scans every pixel
    for the "filled" color (S/V above threshold) and groups matching
    pixels into connected blobs — one blob per actual pip, wherever it
    sits. The pip count is the number of blobs big enough to be a real pip
    (not anti-aliasing noise), left-to-right.

    Returns (level, blobs) where blobs is a list of {h, s, v, area, cx}
    for every accepted blob — used to calibrate pip_threshold_s/v from a
    real capture instead of guessing."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    s_channel = hsv[:, :, 1]
    v_channel = hsv[:, :, 2]
    mask = ((s_channel >= s_threshold) & (v_channel >= v_threshold)).astype(np.uint8) * 255

    total_area = img_bgr.shape[0] * img_bgr.shape[1]
    min_blob_area = max(2, total_area // (max_pips * 20))

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

    blobs = []
    for label in range(1, num_labels):  # label 0 is background
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_blob_area:
            continue
        blob_mask = labels == label
        h_mean = float(hsv[:, :, 0][blob_mask].mean())
        s_mean = float(s_channel[blob_mask].mean())
        v_mean = float(v_channel[blob_mask].mean())
        cx = float(centroids[label][0])
        blobs.append({"h": h_mean, "s": s_mean, "v": v_mean, "area": area, "cx": cx})

    blobs.sort(key=lambda b: b["cx"])
    level = min(len(blobs), max_pips)
    return level, blobs


def detect_enchant(img_bgr: np.ndarray, s_threshold: float, v_threshold: float,
                    max_pips: int = 4):
    level, _ = detect_enchant_debug(img_bgr, s_threshold, v_threshold, max_pips)
    return level


def save_enchant_debug(img_bgr: np.ndarray, blobs: list, level: int) -> None:
    """Dump the exact captured item_enchant zone + found-pip HSV readings
    to disk (overwriting the previous ones) so they can be shared to tune
    pip_threshold_s/v against a real, live capture."""
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

        lines = [f"detected level (найдено закрашенных пипсов): {level}", ""]
        if blobs:
            for i, blob in enumerate(blobs):
                lines.append(
                    f"пипс {i}: H={blob['h']:.1f} S={blob['s']:.1f} V={blob['v']:.1f} "
                    f"площадь={blob['area']}px"
                )
        else:
            lines.append("закрашенных пипсов не найдено (все ниже порога)")
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
    enchant, enchant_blobs = detect_enchant_debug(
        enchant_img,
        config.get("pip_threshold_s", 60),
        config.get("pip_threshold_v", 60),
    )
    save_enchant_debug(enchant_img, enchant_blobs, enchant)
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
        "enchant_blobs": enchant_blobs,
        "price": price,
        "needs_review": needs_review,
    }
