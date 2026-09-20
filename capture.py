"""Screenshot capture + OCR + pip-based enchant detection (ТЗ §6-8)."""
import re

import cv2
import mss
import numpy as np
import pytesseract
from PIL import Image

import storage
from config_io import load_aliases, load_config, load_zones, zones_configured

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


def detect_enchant(img_bgr: np.ndarray, s_threshold: float, v_threshold: float,
                    max_pips: int = 4):
    """The item_enchant zone is the row of 4 diamond pips under the item
    icon (ТЗ §7, Variant B). It's split into `max_pips` equal horizontal
    slots (pip positions are static); a slot counts as filled when it's
    brighter/more saturated than an empty (dark grey) pip. Pips fill
    left-to-right, so counting stops at the first empty slot."""
    h, w = img_bgr.shape[:2]
    slot_w = w / max_pips
    filled = 0
    for i in range(max_pips):
        cx = min(int(slot_w * (i + 0.5)), w - 1)
        x0, x1 = max(cx - 2, 0), min(cx + 3, w)
        sample = img_bgr[:, x0:x1]
        if sample.size == 0:
            continue
        hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
        if hsv[:, :, 1].mean() >= s_threshold and hsv[:, :, 2].mean() >= v_threshold:
            filled += 1
        else:
            break
    return filled


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
    enchant = detect_enchant(
        enchant_img,
        config.get("pip_threshold_s", 60),
        config.get("pip_threshold_v", 60),
    )
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
        "price": price,
        "needs_review": needs_review,
    }
