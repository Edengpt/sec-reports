import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "reports.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            company_name TEXT,
            ticker TEXT,
            title TEXT,
            category TEXT,
            filing_type TEXT,
            filed_date TEXT,
            url TEXT,
            matched_keywords TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def report_exists(report_id):
    conn = get_db()
    row = conn.execute("SELECT 1 FROM reports WHERE id = ?", (report_id,)).fetchone()
    conn.close()
    return row is not None


def insert_report(report):
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO reports
           (id, company_name, ticker, title, category, filing_type, filed_date, url, matched_keywords)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            report["id"],
            report["company_name"],
            report["ticker"],
            report["title"],
            report["category"],
            report["filing_type"],
            report["filed_date"],
            report["url"],
            report["matched_keywords"],
        ),
    )
    conn.commit()
    conn.close()


def get_last_report_date():
    conn = get_db()
    row = conn.execute("SELECT MAX(filed_date) FROM reports").fetchone()
    conn.close()
    return row[0] if row else None


def get_all_reports(limit=300):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM reports ORDER BY filed_date DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_old_reports(days=30):
    conn = get_db()
    conn.execute(
        "DELETE FROM reports WHERE filed_date < date('now', ?)",
        (f"-{days} days",),
    )
    conn.commit()
    conn.close()
