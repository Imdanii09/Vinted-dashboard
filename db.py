import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "vinted_dashboard.db"


def _conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS searches (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                filters     TEXT    NOT NULL,
                domain      TEXT    NOT NULL,
                max_items   INTEGER NOT NULL DEFAULT 500,
                created_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                search_id   INTEGER NOT NULL,
                run_at      TEXT    NOT NULL,
                item_count  INTEGER NOT NULL,
                FOREIGN KEY (search_id) REFERENCES searches(id)
            );

            CREATE TABLE IF NOT EXISTS items (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id       INTEGER NOT NULL,
                vinted_id    INTEGER,
                title        TEXT,
                price        REAL,
                currency     TEXT,
                brand        TEXT,
                size         TEXT,
                condition    TEXT,
                url          TEXT,
                photo_url    TEXT,
                published_at INTEGER,
                scraped_at   TEXT    NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            );
        """)


def save_search(name: str, filters: dict, domain: str, max_items: int) -> int:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO searches (name, filters, domain, max_items, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, json.dumps(filters), domain, max_items, now),
        )
        return cur.lastrowid


def save_run(search_id: int, items: list[dict]) -> int:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO runs (search_id, run_at, item_count) VALUES (?, ?, ?)",
            (search_id, now, len(items)),
        )
        run_id = cur.lastrowid
        conn.executemany(
            """INSERT INTO items
               (run_id, vinted_id, title, price, currency, brand, size,
                condition, url, photo_url, published_at, scraped_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    run_id,
                    i.get("vinted_id"),
                    i.get("title"),
                    i.get("price"),
                    i.get("currency", "EUR"),
                    i.get("brand"),
                    i.get("size"),
                    i.get("condition"),
                    i.get("url"),
                    i.get("photo_url"),
                    i.get("published_at"),
                    now,
                )
                for i in items
            ],
        )
        return run_id


def get_all_searches() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT s.*, COUNT(r.id) AS run_count, MAX(r.run_at) AS last_run
            FROM searches s
            LEFT JOIN runs r ON r.search_id = s.id
            GROUP BY s.id
            ORDER BY s.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_search_by_id(search_id: int) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
        return dict(row) if row else None


def get_runs_for_search(search_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM runs WHERE search_id = ? ORDER BY run_at DESC",
            (search_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_items_for_run(run_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM items WHERE run_id = ?", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_search(search_id: int):
    with _conn() as conn:
        conn.execute(
            "DELETE FROM items WHERE run_id IN (SELECT id FROM runs WHERE search_id = ?)",
            (search_id,),
        )
        conn.execute("DELETE FROM runs WHERE search_id = ?", (search_id,))
        conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))
