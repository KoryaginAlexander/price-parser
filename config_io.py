"""Load/save the small JSON config files described in the ТЗ (§2, §10).

zones.json, aliases.json, enchant_colors.json and config.json all live
next to the .exe (see paths.py) and are created with sane defaults on
first run if missing, so the app never crashes on a fresh install.
"""
import json
import os

from paths import path_in_base

CONFIG_FILE = "config.json"
ZONES_FILE = "zones.json"
ALIASES_FILE = "aliases.json"
ENCHANT_COLORS_FILE = "enchant_colors.json"

DEFAULT_CONFIG = {
    "hotkey_capture": "F8",
    "hotkey_edit_zones": "ctrl+F8",
    "db_path": "%LOCALAPPDATA%/AlbionMarketScanner/data.db",
    "tesseract_path": "C:/Program Files/Tesseract-OCR/tesseract.exe",
    "price_thousands_separator": ",",
    "report_output_dir": "./reports",
}

DEFAULT_ALIASES = {
    "знаток": 4,
    "эксперт": 5,
    "мастер": 6,
    "магистр": 7,
    "старейшина": 8,
}

# Calibrated from real captures of the solid color bar under the item icon
# (not a guess — see the color-bar calibration session). H/S/V are OpenCV
# scale (H: 0-179, S/V: 0-255). "0" has no enchant; "4" is kept even though
# it's rarely needed, since we already have real data for it.
DEFAULT_ENCHANT_COLORS = {
    "0": {"h": 14.9, "s": 80.0, "v": 171.2},
    "1": {"h": 68.0, "s": 178.0, "v": 255.0},
    "2": {"h": 88.0, "s": 109.8, "v": 189.5},
    "3": {"h": 144.0, "s": 111.7, "v": 184.3},
    "4": {"h": 21.4, "s": 120.8, "v": 207.2},
}


def _load_json(filename: str, default: dict) -> dict:
    path = path_in_base(filename)
    if not os.path.exists(path):
        _save_json(filename, default)
        return dict(default)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(filename: str, data: dict) -> None:
    path = path_in_base(filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(_load_json(CONFIG_FILE, DEFAULT_CONFIG))
    return cfg


def save_config(cfg: dict) -> None:
    _save_json(CONFIG_FILE, cfg)


def load_aliases() -> dict:
    return _load_json(ALIASES_FILE, DEFAULT_ALIASES)


def save_aliases(aliases: dict) -> None:
    _save_json(ALIASES_FILE, aliases)


def load_enchant_colors() -> dict:
    return _load_json(ENCHANT_COLORS_FILE, DEFAULT_ENCHANT_COLORS)


def save_enchant_colors(colors: dict) -> None:
    _save_json(ENCHANT_COLORS_FILE, colors)


def load_zones():
    path = path_in_base(ZONES_FILE)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_zones(zones: dict) -> None:
    _save_json(ZONES_FILE, zones)


def zones_configured(zones) -> bool:
    if not zones:
        return False
    required = ("item_name", "item_enchant", "sell_price")
    return all(k in zones and zones[k] for k in required)
