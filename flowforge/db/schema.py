from __future__ import annotations

import re
from pathlib import Path

from .connection import connect


DEFAULT_STATUSES: tuple[dict, ...] = (
    {"key": "planning", "name": "Planning", "position": 0, "is_started": 0, "is_blocked": 0, "is_terminal": 0, "is_reopened": 0},
    {"key": "todo", "name": "Todo", "position": 1, "is_started": 0, "is_blocked": 0, "is_terminal": 0, "is_reopened": 0},
    {"key": "in_progress", "name": "In Progress", "position": 2, "is_started": 1, "is_blocked": 0, "is_terminal": 0, "is_reopened": 0},
    {"key": "review", "name": "Review", "position": 3, "is_started": 1, "is_blocked": 0, "is_terminal": 0, "is_reopened": 0},
    {"key": "done", "name": "Done", "position": 4, "is_started": 1, "is_blocked": 0, "is_terminal": 1, "is_reopened": 0},
    {"key": "blocked", "name": "Blocked", "position": 5, "is_started": 1, "is_blocked": 1, "is_terminal": 0, "is_reopened": 0},
    {"key": "reopened", "name": "Reopened", "position": 6, "is_started": 1, "is_blocked": 0, "is_terminal": 0, "is_reopened": 1},
)


SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS project_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        is_builtin INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS template_statuses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id INTEGER NOT NULL,
        key TEXT NOT NULL,
        name TEXT NOT NULL,
        position INTEGER NOT NULL,
        is_started INTEGER NOT NULL DEFAULT 0,
        is_blocked INTEGER NOT NULL DEFAULT 0,
        is_terminal INTEGER NOT NULL DEFAULT 0,
        is_reopened INTEGER NOT NULL DEFAULT 0,
        UNIQUE(template_id, key),
        FOREIGN KEY(template_id) REFERENCES project_templates(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS template_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id INTEGER NOT NULL,
        status_key TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        priority TEXT NOT NULL DEFAULT 'medium',
        position INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(template_id) REFERENCES project_templates(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT,
        name TEXT NOT NULL,
        description TEXT,
        template_id INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(template_id) REFERENCES project_templates(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_statuses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        key TEXT NOT NULL,
        name TEXT NOT NULL,
        position INTEGER NOT NULL,
        is_started INTEGER NOT NULL DEFAULT 0,
        is_blocked INTEGER NOT NULL DEFAULT 0,
        is_terminal INTEGER NOT NULL DEFAULT 0,
        is_reopened INTEGER NOT NULL DEFAULT 0,
        UNIQUE(project_id, key),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS work_units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        key TEXT,
        title TEXT NOT NULL,
        description TEXT,
        type TEXT NOT NULL DEFAULT 'feature',
        status_id INTEGER,
        priority TEXT NOT NULL DEFAULT 'medium',
        start_date TEXT,
        target_date TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY(status_id) REFERENCES project_statuses(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        work_unit_id INTEGER,
        key TEXT,
        status_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        helpdesk_ref_id TEXT,
        priority TEXT NOT NULL DEFAULT 'medium',
        assignee TEXT,
        due_date TEXT,
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(project_id, helpdesk_ref_id),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY(work_unit_id) REFERENCES work_units(id) ON DELETE SET NULL,
        FOREIGN KEY(status_id) REFERENCES project_statuses(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS task_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        author TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS image_attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        comment_id INTEGER,
        filename TEXT NOT NULL,
        content_type TEXT NOT NULL,
        image_data BLOB NOT NULL,
        size_bytes INTEGER NOT NULL,
        alt_text TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CHECK (
            (task_id IS NOT NULL AND comment_id IS NULL)
            OR (task_id IS NULL AND comment_id IS NOT NULL)
        ),
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
        FOREIGN KEY(comment_id) REFERENCES task_comments(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        normalized_name TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS task_tags (
        task_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL,
        PRIMARY KEY(task_id, tag_id),
        FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
        FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS work_unit_tags (
        work_unit_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL,
        PRIMARY KEY(work_unit_id, tag_id),
        FOREIGN KEY(work_unit_id) REFERENCES work_units(id) ON DELETE CASCADE,
        FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
    )
    """,
)


def initialize(db_path: Path) -> None:
    with connect(db_path) as conn:
        for statement in SCHEMA:
            conn.execute(statement)
        _migrate_entity_keys(conn)
        _initialize_search(conn)
        _seed_builtin_template(conn)


def normalize_entity_key(value: str | None, fallback: str) -> str:
    if value:
        normalized = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().upper()).strip("-")
        if normalized:
            return normalized
    return fallback


def default_entity_key(value: str | None, fallback: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", value or "")
    if not tokens:
        return fallback
    if len(tokens) == 1:
        return normalize_entity_key(tokens[0], fallback)
    parts = []
    for token in tokens:
        lowered = token.lower()
        if lowered.startswith("v") and token[1:].isdigit():
            parts.append(token[1:])
        elif token.isdigit():
            parts.append(token)
        else:
            parts.append(token[0])
    return normalize_entity_key("".join(parts), fallback)


def _migrate_entity_keys(conn) -> None:
    _ensure_column(conn, "projects", "key", "TEXT")
    _ensure_column(conn, "work_units", "key", "TEXT")
    _ensure_column(conn, "tasks", "key", "TEXT")
    _backfill_project_keys(conn)
    _backfill_work_unit_keys(conn)
    _backfill_task_keys(conn)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_key ON projects(key)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_work_units_project_key ON work_units(project_id, key)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_project_key ON tasks(project_id, key)")


def _ensure_column(conn, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _backfill_project_keys(conn) -> None:
    used: set[str] = set()
    rows = conn.execute("SELECT id, key, name FROM projects ORDER BY id").fetchall()
    for row in rows:
        base = normalize_entity_key(row["key"], default_entity_key(row["name"], "PROJECT"))
        key = _unique_key(base, used)
        used.add(key)
        if row["key"] != key:
            conn.execute("UPDATE projects SET key = ? WHERE id = ?", (key, row["id"]))


def _backfill_work_unit_keys(conn) -> None:
    used_by_project: dict[int, set[str]] = {}
    rows = conn.execute(
        "SELECT id, project_id, key, title FROM work_units ORDER BY project_id, created_at, id"
    ).fetchall()
    for row in rows:
        used = used_by_project.setdefault(int(row["project_id"]), set())
        base = normalize_entity_key(row["key"], default_entity_key(row["title"], "WU"))
        key = _unique_key(base, used)
        used.add(key)
        if row["key"] != key:
            conn.execute("UPDATE work_units SET key = ? WHERE id = ?", (key, row["id"]))


def _backfill_task_keys(conn) -> None:
    counters: dict[tuple[int, str], int] = {}
    used_by_project: dict[int, set[str]] = {}
    rows = conn.execute(
        """
        SELECT
            t.id,
            t.project_id,
            t.work_unit_id,
            t.key,
            p.key AS project_key,
            wu.key AS work_unit_key
        FROM tasks t
        JOIN projects p ON p.id = t.project_id
        LEFT JOIN work_units wu ON wu.id = t.work_unit_id
        ORDER BY t.project_id, COALESCE(t.work_unit_id, 0), t.created_at, t.id
        """
    ).fetchall()
    for row in rows:
        project_id = int(row["project_id"])
        used = used_by_project.setdefault(project_id, set())
        if row["key"]:
            key = _unique_key(normalize_entity_key(row["key"], "TASK"), used)
        else:
            prefix = normalize_entity_key(row["work_unit_key"] or row["project_key"], "TASK")
            counter_key = (project_id, prefix)
            counters[counter_key] = counters.get(counter_key, 0) + 1
            key = _unique_key(f"{prefix}-{counters[counter_key]}", used)
        used.add(key)
        if row["key"] != key:
            conn.execute("UPDATE tasks SET key = ? WHERE id = ?", (key, row["id"]))


def _unique_key(base: str, used: set[str]) -> str:
    key = base
    suffix = 2
    while key in used:
        key = f"{base}{suffix}"
        suffix += 1
    return key


def _initialize_search(conn) -> None:
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
                entity_type,
                entity_id UNINDEXED,
                project_id UNINDEXED,
                title,
                body,
                tags,
                helpdesk_ref_id
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO search_meta (key, value) VALUES ('fts5_available', '1')"
        )
    except Exception:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO search_meta (key, value) VALUES ('fts5_available', '0')"
        )


def _seed_builtin_template(conn) -> None:
    cursor = conn.execute("SELECT id FROM project_templates WHERE name = ?", ("Default",))
    if cursor.fetchone() is not None:
        return
    template_cursor = conn.execute(
        """
        INSERT INTO project_templates (name, description, is_builtin)
        VALUES (?, ?, 1)
        """,
        ("Default", "Default FlowForge project workflow."),
    )
    template_id = int(template_cursor.lastrowid)
    conn.executemany(
        """
        INSERT INTO template_statuses
        (template_id, key, name, position, is_started, is_blocked, is_terminal, is_reopened)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                template_id,
                status["key"],
                status["name"],
                status["position"],
                status["is_started"],
                status["is_blocked"],
                status["is_terminal"],
                status["is_reopened"],
            )
            for status in DEFAULT_STATUSES
        ],
    )

