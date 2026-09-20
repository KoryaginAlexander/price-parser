"""Filesystem paths that must resolve correctly both in dev (python main.py)
and when frozen into a single .exe with PyInstaller (--onefile)."""
import os
import sys


def base_dir() -> str:
    """Directory next to the executable when frozen, or next to this
    script during development. All JSON config files live here so that
    zone_editor.py can persist edits between runs of the built .exe."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def path_in_base(filename: str) -> str:
    return os.path.join(base_dir(), filename)


def resource_path(relative_path: str) -> str:
    """Static bundled assets (e.g. sound effects). Unlike base_dir(), these
    are baked into the onefile .exe and read from PyInstaller's temp
    extraction dir (sys._MEIPASS) at runtime, never edited by the user."""
    if getattr(sys, "frozen", False):
        root = getattr(sys, "_MEIPASS", base_dir())
    else:
        root = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(root, relative_path)
