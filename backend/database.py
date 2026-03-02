"""SQLite schema and helpers for analysis history."""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    format TEXT NOT NULL,
    verdict TEXT NOT NULL,
    score REAL NOT NULL,
    diagnostic TEXT,
    analyzed_at TEXT NOT NULL,
    duration_sec REAL,
    bitrate_kbps REAL,
    actual_bitrate_kbps INTEGER,
    clipping_pct REAL,
    peak_dbfs REAL
);
CREATE INDEX IF NOT EXISTS idx_analyzed_at ON analyses(analyzed_at);
CREATE INDEX IF NOT EXISTS idx_verdict ON analyses(verdict);
"""

def _migrate_add_columns(conn: sqlite3.Connection) -> None:
    """Add new metric columns if they don't exist (for existing DBs)."""
    cur = conn.execute("PRAGMA table_info(analyses)")
    names = {row[1] for row in cur.fetchall()}
    adds = [
        ("duration_sec", "REAL"),
        ("bitrate_kbps", "REAL"),
        ("actual_bitrate_kbps", "INTEGER"),
        ("clipping_pct", "REAL"),
        ("peak_dbfs", "REAL"),
        ("lexicon_track_id", "INTEGER"),
    ]
    for col, typ in adds:
        if col not in names:
            try:
                conn.execute(f"ALTER TABLE analyses ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                pass


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(_SCHEMA)
        _migrate_add_columns(conn)


def insert_analysis(
    file_path: str,
    file_name: str,
    file_size: int,
    format: str,
    verdict: str,
    score: float,
    diagnostic: Optional[str] = None,
    duration_sec: Optional[float] = None,
    bitrate_kbps: Optional[float] = None,
    actual_bitrate_kbps: Optional[int] = None,
    clipping_pct: Optional[float] = None,
    peak_dbfs: Optional[float] = None,
    lexicon_track_id: Optional[int] = None,
) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO analyses (file_path, file_name, file_size, format, verdict, score, diagnostic, analyzed_at,
                duration_sec, bitrate_kbps, actual_bitrate_kbps, clipping_pct, peak_dbfs, lexicon_track_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_path, file_name, file_size, format, verdict, score, diagnostic or "",
                datetime.utcnow().isoformat() + "Z",
                duration_sec, bitrate_kbps, actual_bitrate_kbps, clipping_pct, peak_dbfs,
                lexicon_track_id,
            ),
        )
        return cur.lastrowid or 0


def get_history(
    search: Optional[str] = None,
    verdict: Optional[str] = None,
    limit: int = 500,
) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conditions = []
        params = []
        if search and search.strip():
            conditions.append("(file_name LIKE ? OR diagnostic LIKE ?)")
            params.extend([f"%{search.strip()}%", f"%{search.strip()}%"])
        if verdict and verdict.strip().lower() in ("fake", "suspicious", "real"):
            conditions.append("verdict = ?")
            params.append(verdict.strip().lower())
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        cur = conn.execute(
            f"""
            SELECT id, file_path, file_name, file_size, format, verdict, score, diagnostic, analyzed_at,
                duration_sec, bitrate_kbps, actual_bitrate_kbps, clipping_pct, peak_dbfs, lexicon_track_id
            FROM analyses
            {where}
            ORDER BY analyzed_at DESC
            LIMIT ?
            """,
            params,
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_all_for_export() -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """SELECT file_path, file_name, file_size, format, verdict, score, diagnostic, analyzed_at,
                duration_sec, bitrate_kbps, actual_bitrate_kbps, clipping_pct, peak_dbfs, lexicon_track_id
            FROM analyses ORDER BY analyzed_at DESC"""
        )
        return [dict(r) for r in cur.fetchall()]


def clear_history() -> int:
    """Delete all analysis records. Returns number of rows deleted."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("DELETE FROM analyses")
        n = cur.rowcount
        conn.commit()
        return n


def get_lexicon_track_ids_by_verdict() -> dict:
    """
    Return analyses that have lexicon_track_id set, grouped by verdict.
    Keys: "fake", "suspicious". Values: list of Lexicon track IDs (int).
    """
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            SELECT verdict, lexicon_track_id FROM analyses
            WHERE lexicon_track_id IS NOT NULL AND verdict IN ('fake', 'suspicious')
            ORDER BY analyzed_at DESC
            """
        )
        rows = cur.fetchall()
    by_verdict = {"fake": [], "suspicious": []}
    seen = set()
    for verdict, lid in rows:
        if lid is None or (verdict, lid) in seen:
            continue
        seen.add((verdict, lid))
        if verdict in by_verdict:
            by_verdict[verdict].append(lid)
    return by_verdict
