import sqlite3
import json
import os
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = os.getenv("DB_PATH", str(Path(__file__).parent / "context.db"))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS repositories (
            repo_name       TEXT PRIMARY KEY,
            full_name       TEXT,
            description     TEXT,
            language        TEXT,
            topics          TEXT,
            readme_md       TEXT,
            key_features    TEXT,
            significance    INTEGER DEFAULT 5,
            stars           INTEGER DEFAULT 0,
            created_at      TEXT,
            first_seen      TEXT,
            last_pushed     TEXT
        );

        CREATE TABLE IF NOT EXISTS linkedin_posts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_name   TEXT,
            post_text   TEXT NOT NULL,
            post_urn    TEXT,
            posted_at   TEXT NOT NULL,
            tone        TEXT,
            themes      TEXT,
            hashtags    TEXT,
            has_image   INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tweets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_name   TEXT,
            tweet_text  TEXT NOT NULL,
            tweet_id    TEXT,
            posted_at   TEXT NOT NULL,
            hook_type   TEXT,
            hashtags    TEXT,
            has_image   INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS resume_versions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            version             INTEGER NOT NULL,
            markdown_content    TEXT NOT NULL,
            pdf_path            TEXT,
            change_summary      TEXT,
            created_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS run_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at          TEXT NOT NULL,
            trigger         TEXT DEFAULT 'scheduled',
            new_repos       TEXT,
            actions_taken   TEXT,
            errors          TEXT,
            duration_s      REAL
        );

        CREATE TABLE IF NOT EXISTS agent_context (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ── Repositories ──────────────────────────────────────────────────────────────

def get_known_repo_names() -> set[str]:
    conn = get_conn()
    rows = conn.execute("SELECT repo_name FROM repositories").fetchall()
    conn.close()
    return {r["repo_name"] for r in rows}


def get_repo_last_pushed(repo_name: str) -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT last_pushed FROM repositories WHERE repo_name = ?", (repo_name,)
    ).fetchone()
    conn.close()
    return row["last_pushed"] if row else None


def save_repository(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO repositories
            (repo_name, full_name, description, language, topics, readme_md,
             key_features, significance, stars, created_at, first_seen, last_pushed)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(repo_name) DO UPDATE SET
            description = excluded.description,
            language    = excluded.language,
            topics      = excluded.topics,
            readme_md   = excluded.readme_md,
            key_features = excluded.key_features,
            stars       = excluded.stars,
            last_pushed = excluded.last_pushed
    """, (
        data["repo_name"], data.get("full_name"), data.get("description"),
        data.get("language"), json.dumps(data.get("topics", [])),
        data.get("readme_md"), json.dumps(data.get("key_features", [])),
        data.get("significance", 5), data.get("stars", 0),
        data.get("created_at"), data.get("first_seen", _now()),
        data.get("last_pushed"),
    ))
    conn.commit()
    conn.close()


def update_repo_significance(repo_name: str, score: int):
    conn = get_conn()
    conn.execute(
        "UPDATE repositories SET significance = ? WHERE repo_name = ?",
        (score, repo_name)
    )
    conn.commit()
    conn.close()


def get_all_repos() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM repositories ORDER BY significance DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── LinkedIn posts ─────────────────────────────────────────────────────────────

def save_linkedin_post(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO linkedin_posts (repo_name, post_text, post_urn, posted_at, tone, themes, hashtags, has_image)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        data.get("repo_name"), data["post_text"], data.get("post_urn"),
        data.get("posted_at", _now()), data.get("tone"),
        json.dumps(data.get("themes", [])), json.dumps(data.get("hashtags", [])),
        int(data.get("has_image", False)),
    ))
    conn.commit()
    conn.close()


def get_recent_linkedin_posts(n: int = 20) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM linkedin_posts ORDER BY posted_at DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def days_since_last_linkedin_post_for_repo(repo_name: str) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT posted_at FROM linkedin_posts WHERE repo_name = ? ORDER BY posted_at DESC LIMIT 1",
        (repo_name,)
    ).fetchone()
    conn.close()
    if not row:
        return 999
    delta = datetime.now(timezone.utc) - datetime.fromisoformat(row["posted_at"])
    return delta.days


# ── Tweets ─────────────────────────────────────────────────────────────────────

def save_tweet(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO tweets (repo_name, tweet_text, tweet_id, posted_at, hook_type, hashtags, has_image)
        VALUES (?,?,?,?,?,?,?)
    """, (
        data.get("repo_name"), data["tweet_text"], data.get("tweet_id"),
        data.get("posted_at", _now()), data.get("hook_type"),
        json.dumps(data.get("hashtags", [])), int(data.get("has_image", False)),
    ))
    conn.commit()
    conn.close()


def get_recent_tweets(n: int = 20) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM tweets ORDER BY posted_at DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Resume versions ─────────────────────────────────────────────────────────────

def save_resume_version(markdown_content: str, pdf_path: str, change_summary: str) -> int:
    conn = get_conn()
    row = conn.execute("SELECT MAX(version) as v FROM resume_versions").fetchone()
    version = (row["v"] or 0) + 1
    conn.execute("""
        INSERT INTO resume_versions (version, markdown_content, pdf_path, change_summary, created_at)
        VALUES (?,?,?,?,?)
    """, (version, markdown_content, pdf_path, change_summary, _now()))
    conn.commit()
    conn.close()
    return version


def get_current_resume_markdown() -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT markdown_content FROM resume_versions ORDER BY version DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["markdown_content"] if row else None


def get_resume_version(version: int) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM resume_versions WHERE version = ?", (version,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Run log ────────────────────────────────────────────────────────────────────

def log_run(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO run_log (run_at, trigger, new_repos, actions_taken, errors, duration_s)
        VALUES (?,?,?,?,?,?)
    """, (
        data.get("run_at", _now()), data.get("trigger", "scheduled"),
        json.dumps(data.get("new_repos", [])),
        json.dumps(data.get("actions_taken", [])),
        json.dumps(data.get("errors", [])),
        data.get("duration_s"),
    ))
    conn.commit()
    conn.close()


# ── Agent context ──────────────────────────────────────────────────────────────

def get_context(key: str) -> str | None:
    conn = get_conn()
    row = conn.execute("SELECT value FROM agent_context WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_context(key: str, value: str):
    conn = get_conn()
    conn.execute("""
        INSERT INTO agent_context (key, value, updated_at) VALUES (?,?,?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
    """, (key, value, _now()))
    conn.commit()
    conn.close()


def get_full_context() -> dict:
    return {
        "all_repos": get_all_repos(),
        "recent_linkedin_posts": get_recent_linkedin_posts(20),
        "recent_tweets": get_recent_tweets(20),
        "narrative_arc": get_context("narrative_arc") or "",
        "skills_mentioned": get_context("skills_mentioned") or "[]",
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
