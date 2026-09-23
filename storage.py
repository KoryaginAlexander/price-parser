"""SQLite storage — upsert-only, no price history (ТЗ §8 schema, §12)."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class TEXT NOT NULL,
    item_name TEXT NOT NULL,
    tier INTEGER NOT NULL,
    enchant INTEGER NOT NULL,
    price INTEGER NOT NULL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(class, item_name, tier, enchant)
);
"""

# SQLite treats NULL as distinct from NULL in a UNIQUE index, which would
# defeat the "no duplicates" upsert requirement (ТЗ §8/§13.8) whenever an
# alias can't be resolved. Unresolved tier is stored as -1 (needs_review=1)
# instead of NULL; reports render -1 as "?".
UNKNOWN_TIER = -1


def resolve_db_path(db_path_template: str) -> str:
    expanded = os.path.expandvars(db_path_template)
    expanded = os.path.normpath(expanded)
    os.makedirs(os.path.dirname(expanded), exist_ok=True)
    return expanded


@contextmanager
def get_connection(db_path: str):
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with get_connection(db_path) as conn:
        conn.execute(SCHEMA)
        conn.commit()


def upsert_item(db_path: str, item_class: str, item_name: str, tier, enchant: int,
                 price, needs_review: bool) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    tier_value = UNKNOWN_TIER if tier is None else int(tier)
    price_value = 0 if price is None else int(price)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO items (class, item_name, tier, enchant, price, needs_review, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(class, item_name, tier, enchant)
            DO UPDATE SET price=excluded.price,
                          needs_review=excluded.needs_review,
                          updated_at=excluded.updated_at
            """,
            (item_class, item_name, tier_value, int(enchant), price_value, int(needs_review), now),
        )
        conn.commit()


def fetch_by_class(db_path: str, item_class: str):
    with get_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT item_name, tier, enchant, price, needs_review, updated_at "
            "FROM items WHERE class = ? ORDER BY updated_at DESC",
            (item_class,),
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_all(db_path: str):
    with get_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM items ORDER BY class, item_name")
        return [dict(row) for row in cur.fetchall()]


def fetch_filtered(db_path: str, item_class=None, tier=None, enchant=None, name_query=None):
    """class/tier/enchant are exact-match filters done in SQL; name_query is
    a case-insensitive substring match done in Python (SQLite's LIKE only
    case-folds ASCII, so it can't match Cyrillic 'мант' against 'Мантия')."""
    query = "SELECT * FROM items WHERE 1=1"
    params = []
    if item_class:
        query += " AND class = ?"
        params.append(item_class)
    if tier is not None:
        query += " AND tier = ?"
        params.append(tier)
    if enchant is not None:
        query += " AND enchant = ?"
        params.append(enchant)
    query += " ORDER BY class, item_name, tier, enchant"

    with get_connection(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(query, params)
        rows = [dict(row) for row in cur.fetchall()]

    if name_query:
        needle = name_query.strip().lower()
        rows = [r for r in rows if needle in r["item_name"].lower()]
    return rows


def delete_by_id(db_path: str, item_id: int) -> None:
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.commit()
