from __future__ import annotations

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
        _initialize_search(conn)
        _seed_builtin_template(conn)


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

