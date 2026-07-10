from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .config import FlowForgeConfig
from .db.connection import connect, rows_to_dicts
from .db.schema import DEFAULT_STATUSES, initialize
from .models import (
    CreateComment,
    CreateProject,
    CreateProjectTemplate,
    CreateTask,
    CreateWorkUnit,
    UpdateComment,
    UpdateProject,
    UpdateTask,
    UpdateWorkUnit,
)


def normalize_tag(name: str) -> str:
    return " ".join(name.strip().lower().split())


def normalize_status_key(name: str) -> str:
    return "_".join(name.strip().lower().split())


class FlowForgeService:
    def __init__(self, config: FlowForgeConfig | None = None):
        self.config = config or FlowForgeConfig.from_env()
        self.config.ensure_dirs()
        initialize(self.config.db_path)

    @classmethod
    def for_path(cls, db_path: Path) -> "FlowForgeService":
        return cls(FlowForgeConfig(db_path=db_path))

    def list_templates(self) -> list[dict]:
        with connect(self.config.db_path) as conn:
            templates = rows_to_dicts(conn.execute("SELECT * FROM project_templates ORDER BY name").fetchall())
            for template in templates:
                template["statuses"] = rows_to_dicts(
                    conn.execute(
                        "SELECT key, name, position, is_started, is_blocked, is_terminal, is_reopened FROM template_statuses WHERE template_id = ? ORDER BY position",
                        (template["id"],),
                    ).fetchall()
                )
                template["starter_tasks"] = rows_to_dicts(
                    conn.execute(
                        "SELECT status_key, title, description, priority, position FROM template_tasks WHERE template_id = ? ORDER BY position",
                        (template["id"],),
                    ).fetchall()
                )
        return templates

    def create_project_template(self, payload: CreateProjectTemplate | dict) -> dict:
        payload = CreateProjectTemplate.model_validate(payload)
        statuses = payload.statuses or list(DEFAULT_STATUSES)
        with connect(self.config.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO project_templates (name, description, is_builtin) VALUES (?, ?, 0)",
                (payload.name, payload.description),
            )
            template_id = int(cursor.lastrowid)
            for index, status in enumerate(statuses):
                key = status.get("key") or normalize_status_key(status["name"])
                conn.execute(
                    """
                    INSERT INTO template_statuses
                    (template_id, key, name, position, is_started, is_blocked, is_terminal, is_reopened)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        template_id,
                        key,
                        status["name"],
                        status.get("position", index),
                        int(status.get("is_started", 0)),
                        int(status.get("is_blocked", 0)),
                        int(status.get("is_terminal", 0)),
                        int(status.get("is_reopened", 0)),
                    ),
                )
            for index, task in enumerate(payload.starter_tasks):
                conn.execute(
                    """
                    INSERT INTO template_tasks (template_id, status_key, title, description, priority, position)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        template_id,
                        task.get("status_key", "todo"),
                        task["title"],
                        task.get("description"),
                        task.get("priority", "medium"),
                        task.get("position", index),
                    ),
                )
        return self.get_template(template_id)

    def get_template(self, template_id: int) -> dict:
        return next(template for template in self.list_templates() if template["id"] == template_id)

    def create_project(self, payload: CreateProject | dict) -> dict:
        payload = CreateProject.model_validate(payload)
        with connect(self.config.db_path) as conn:
            template_id = payload.template_id or self._default_template_id(conn)
            cursor = conn.execute(
                "INSERT INTO projects (name, description, template_id) VALUES (?, ?, ?)",
                (payload.name, payload.description, template_id),
            )
            project_id = int(cursor.lastrowid)
            status_id_by_key = self._seed_project_statuses(conn, project_id, template_id)
            self._seed_project_tasks(conn, project_id, template_id, status_id_by_key)
            self._refresh_project_search(conn, project_id)
        return self.get_project(project_id)

    def list_projects(self, search: str | None = None) -> list[dict]:
        sql = "SELECT * FROM projects"
        params: list[Any] = []
        if search:
            sql += " WHERE LOWER(name) LIKE ? OR LOWER(COALESCE(description, '')) LIKE ?"
            term = f"%{search.lower()}%"
            params.extend([term, term])
        sql += " ORDER BY updated_at DESC, id DESC"
        with connect(self.config.db_path) as conn:
            return rows_to_dicts(conn.execute(sql, params).fetchall())

    def get_project(self, project_id: int) -> dict:
        with connect(self.config.db_path) as conn:
            project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if project is None:
                raise ValueError(f"Project {project_id} not found.")
            result = dict(project)
            result["statuses"] = self.list_project_statuses(project_id)
        return result

    def update_project(self, project_id: int, payload: UpdateProject | dict) -> dict:
        payload = UpdateProject.model_validate(payload)
        updates = payload.model_dump(exclude_unset=True)
        if updates:
            self._update_row("projects", project_id, updates)
        return self.get_project(project_id)

    def list_project_statuses(self, project_id: int) -> list[dict]:
        with connect(self.config.db_path) as conn:
            return rows_to_dicts(
                conn.execute(
                    "SELECT * FROM project_statuses WHERE project_id = ? ORDER BY position",
                    (project_id,),
                ).fetchall()
            )

    def create_work_unit(self, payload: CreateWorkUnit | dict) -> dict:
        payload = CreateWorkUnit.model_validate(payload)
        with connect(self.config.db_path) as conn:
            status_id = self._status_id(conn, payload.project_id, payload.status or "Planning")
            cursor = conn.execute(
                """
                INSERT INTO work_units
                (project_id, title, description, type, status_id, priority, start_date, target_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.project_id,
                    payload.title,
                    payload.description,
                    payload.type,
                    status_id,
                    payload.priority,
                    payload.start_date,
                    payload.target_date,
                ),
            )
            work_unit_id = int(cursor.lastrowid)
            self._set_tags(conn, "work_unit", work_unit_id, payload.tags)
            self._refresh_project_search(conn, payload.project_id)
        return self.get_work_unit(work_unit_id)

    def list_work_units(
        self,
        project_id: int | None = None,
        status: str | None = None,
        priority: str | None = None,
        tag: str | None = None,
        search: str | None = None,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append("wu.project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("LOWER(ps.name) = ?")
            params.append(status.lower())
        if priority:
            clauses.append("wu.priority = ?")
            params.append(priority)
        if search:
            clauses.append("(LOWER(wu.title) LIKE ? OR LOWER(COALESCE(wu.description, '')) LIKE ?)")
            term = f"%{search.lower()}%"
            params.extend([term, term])
        sql = """
            SELECT wu.*, ps.name AS status, ps.key AS status_key
            FROM work_units wu
            LEFT JOIN project_statuses ps ON ps.id = wu.status_id
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY wu.updated_at DESC, wu.id DESC"
        with connect(self.config.db_path) as conn:
            work_units = [self._decorate_work_unit(conn, row) for row in conn.execute(sql, params).fetchall()]
        if tag:
            normalized = normalize_tag(tag)
            work_units = [unit for unit in work_units if normalized in [normalize_tag(item) for item in unit["tags"]]]
        return work_units

    def get_work_unit(self, work_unit_id: int) -> dict:
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                """
                SELECT wu.*, ps.name AS status, ps.key AS status_key
                FROM work_units wu
                LEFT JOIN project_statuses ps ON ps.id = wu.status_id
                WHERE wu.id = ?
                """,
                (work_unit_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Work unit {work_unit_id} not found.")
            result = self._decorate_work_unit(conn, row)
            result["progress"] = self.get_work_unit_progress(work_unit_id)
        return result

    def update_work_unit(self, work_unit_id: int, payload: UpdateWorkUnit | dict) -> dict:
        payload = UpdateWorkUnit.model_validate(payload)
        updates = payload.model_dump(exclude_unset=True)
        tags = updates.pop("tags", None)
        with connect(self.config.db_path) as conn:
            row = conn.execute("SELECT * FROM work_units WHERE id = ?", (work_unit_id,)).fetchone()
            if row is None:
                raise ValueError(f"Work unit {work_unit_id} not found.")
            if "status" in updates:
                updates["status_id"] = self._status_id(conn, row["project_id"], updates.pop("status"))
            if updates:
                self._update_row_with_conn(conn, "work_units", work_unit_id, updates)
            if tags is not None:
                self._set_tags(conn, "work_unit", work_unit_id, tags)
            self._refresh_project_search(conn, row["project_id"])
        return self.get_work_unit(work_unit_id)

    def get_work_unit_progress(self, work_unit_id: int) -> dict:
        with connect(self.config.db_path) as conn:
            rows = conn.execute(
                """
                SELECT ps.is_terminal
                FROM tasks t
                JOIN project_statuses ps ON ps.id = t.status_id
                WHERE t.work_unit_id = ?
                """,
                (work_unit_id,),
            ).fetchall()
        total = len(rows)
        completed = sum(1 for row in rows if row["is_terminal"])
        percent = 0 if total == 0 else round((completed / total) * 100)
        return {"work_unit_id": work_unit_id, "total_tasks": total, "completed_tasks": completed, "progress_percent": percent}

    def create_task(self, payload: CreateTask | dict) -> dict:
        payload = CreateTask.model_validate(payload)
        with connect(self.config.db_path) as conn:
            status_id = self._status_id(conn, payload.project_id, payload.status)
            position = payload.position
            if position is None:
                position = self._next_task_position(conn, payload.project_id, status_id)
            cursor = conn.execute(
                """
                INSERT INTO tasks
                (project_id, work_unit_id, status_id, title, description, helpdesk_ref_id, priority, assignee, due_date, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.project_id,
                    payload.work_unit_id,
                    status_id,
                    payload.title,
                    payload.description,
                    payload.helpdesk_ref_id,
                    payload.priority,
                    payload.assignee,
                    payload.due_date,
                    position,
                ),
            )
            task_id = int(cursor.lastrowid)
            self._set_tags(conn, "task", task_id, payload.tags)
            self._refresh_project_search(conn, payload.project_id)
        return self.get_task(task_id)

    def list_tasks(
        self,
        project_id: int | None = None,
        status: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        work_unit_id: int | None = None,
        tag: str | None = None,
        helpdesk_ref_id: str | None = None,
        search: str | None = None,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append("t.project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("LOWER(ps.name) = ?")
            params.append(status.lower())
        if priority:
            clauses.append("t.priority = ?")
            params.append(priority)
        if assignee:
            clauses.append("LOWER(COALESCE(t.assignee, '')) = ?")
            params.append(assignee.lower())
        if work_unit_id is not None:
            clauses.append("t.work_unit_id = ?")
            params.append(work_unit_id)
        if helpdesk_ref_id:
            clauses.append("LOWER(COALESCE(t.helpdesk_ref_id, '')) = ?")
            params.append(helpdesk_ref_id.lower())
        if search:
            clauses.append("(LOWER(t.title) LIKE ? OR LOWER(COALESCE(t.description, '')) LIKE ? OR LOWER(COALESCE(t.helpdesk_ref_id, '')) LIKE ?)")
            term = f"%{search.lower()}%"
            params.extend([term, term, term])
        sql = """
            SELECT t.*, ps.name AS status, ps.key AS status_key, wu.title AS work_unit_title
            FROM tasks t
            JOIN project_statuses ps ON ps.id = t.status_id
            LEFT JOIN work_units wu ON wu.id = t.work_unit_id
        """
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ps.position, t.position, t.updated_at DESC, t.id DESC"
        with connect(self.config.db_path) as conn:
            tasks = [self._decorate_task(conn, row) for row in conn.execute(sql, params).fetchall()]
        if tag:
            normalized = normalize_tag(tag)
            tasks = [task for task in tasks if normalized in [normalize_tag(item) for item in task["tags"]]]
        return tasks

    def get_task(self, task_id: int) -> dict:
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                """
                SELECT t.*, ps.name AS status, ps.key AS status_key, wu.title AS work_unit_title
                FROM tasks t
                JOIN project_statuses ps ON ps.id = t.status_id
                LEFT JOIN work_units wu ON wu.id = t.work_unit_id
                WHERE t.id = ?
                """,
                (task_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Task {task_id} not found.")
            result = self._decorate_task(conn, row)
            result["comments"] = self.list_task_comments(task_id)
        return result

    def get_task_by_helpdesk_ref(self, project_id: int, helpdesk_ref_id: str) -> dict:
        matches = self.list_tasks(project_id=project_id, helpdesk_ref_id=helpdesk_ref_id)
        if not matches:
            raise ValueError(f"Task with helpdesk_ref_id {helpdesk_ref_id!r} not found in project {project_id}.")
        return self.get_task(matches[0]["id"])

    def update_task(self, task_id: int, payload: UpdateTask | dict) -> dict:
        payload = UpdateTask.model_validate(payload)
        updates = payload.model_dump(exclude_unset=True)
        tags = updates.pop("tags", None)
        with connect(self.config.db_path) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise ValueError(f"Task {task_id} not found.")
            if "status" in updates:
                updates["status_id"] = self._status_id(conn, row["project_id"], updates.pop("status"))
            if updates:
                self._update_row_with_conn(conn, "tasks", task_id, updates)
            if tags is not None:
                self._set_tags(conn, "task", task_id, tags)
            self._refresh_project_search(conn, row["project_id"])
        return self.get_task(task_id)

    def delete_task(self, task_id: int) -> dict:
        with connect(self.config.db_path) as conn:
            row = conn.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise ValueError(f"Task {task_id} not found.")
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            self._refresh_project_search(conn, row["project_id"])
        return {"task_id": task_id, "deleted": True}

    def reorder_tasks(self, status: str, task_ids: list[int], project_id: int | None = None) -> dict:
        with connect(self.config.db_path) as conn:
            project_ids = set()
            for position, task_id in enumerate(task_ids):
                row = conn.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if row is None:
                    raise ValueError(f"Task {task_id} not found.")
                task_project_id = int(row["project_id"])
                if project_id is not None and task_project_id != project_id:
                    raise ValueError(f"Task {task_id} is not in project {project_id}.")
                status_id = self._status_id(conn, task_project_id, status)
                conn.execute(
                    "UPDATE tasks SET status_id = ?, position = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status_id, position, task_id),
                )
                project_ids.add(task_project_id)
            for touched_project_id in project_ids:
                self._refresh_project_search(conn, touched_project_id)
        return {"status": status, "task_ids": task_ids, "reordered": True}

    def create_task_comment(self, payload: CreateComment | dict) -> dict:
        payload = CreateComment.model_validate(payload)
        with connect(self.config.db_path) as conn:
            task = conn.execute("SELECT project_id FROM tasks WHERE id = ?", (payload.task_id,)).fetchone()
            if task is None:
                raise ValueError(f"Task {payload.task_id} not found.")
            cursor = conn.execute(
                "INSERT INTO task_comments (task_id, content, author) VALUES (?, ?, ?)",
                (payload.task_id, payload.content, payload.author),
            )
            comment_id = int(cursor.lastrowid)
            self._refresh_project_search(conn, task["project_id"])
        return self.get_task_comment(comment_id)

    def list_task_comments(self, task_id: int) -> list[dict]:
        with connect(self.config.db_path) as conn:
            return rows_to_dicts(
                conn.execute(
                    "SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at, id",
                    (task_id,),
                ).fetchall()
            )

    def get_task_comment(self, comment_id: int) -> dict:
        with connect(self.config.db_path) as conn:
            row = conn.execute("SELECT * FROM task_comments WHERE id = ?", (comment_id,)).fetchone()
            if row is None:
                raise ValueError(f"Comment {comment_id} not found.")
            return dict(row)

    def update_task_comment(self, comment_id: int, payload: UpdateComment | dict) -> dict:
        payload = UpdateComment.model_validate(payload)
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                """
                SELECT t.project_id
                FROM task_comments c
                JOIN tasks t ON t.id = c.task_id
                WHERE c.id = ?
                """,
                (comment_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Comment {comment_id} not found.")
            conn.execute(
                "UPDATE task_comments SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (payload.content, comment_id),
            )
            self._refresh_project_search(conn, row["project_id"])
        return self.get_task_comment(comment_id)

    def delete_task_comment(self, comment_id: int) -> dict:
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                """
                SELECT t.project_id
                FROM task_comments c
                JOIN tasks t ON t.id = c.task_id
                WHERE c.id = ?
                """,
                (comment_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Comment {comment_id} not found.")
            conn.execute("DELETE FROM task_comments WHERE id = ?", (comment_id,))
            self._refresh_project_search(conn, row["project_id"])
        return {"comment_id": comment_id, "deleted": True}

    def create_tag(self, name: str) -> dict:
        with connect(self.config.db_path) as conn:
            return self._ensure_tag(conn, name)

    def list_tags(self, search: str | None = None) -> list[dict]:
        sql = "SELECT * FROM tags"
        params: list[Any] = []
        if search:
            sql += " WHERE normalized_name LIKE ?"
            params.append(f"%{normalize_tag(search)}%")
        sql += " ORDER BY normalized_name"
        with connect(self.config.db_path) as conn:
            return rows_to_dicts(conn.execute(sql, params).fetchall())

    def rename_tag(self, tag_id: int, name: str) -> dict:
        normalized = normalize_tag(name)
        with connect(self.config.db_path) as conn:
            conn.execute(
                "UPDATE tags SET name = ?, normalized_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (name.strip(), normalized, tag_id),
            )
            row = conn.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
            if row is None:
                raise ValueError(f"Tag {tag_id} not found.")
            for project in conn.execute("SELECT id FROM projects").fetchall():
                self._refresh_project_search(conn, project["id"])
            return dict(row)

    def delete_tag(self, tag_id: int) -> dict:
        with connect(self.config.db_path) as conn:
            conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
            for project in conn.execute("SELECT id FROM projects").fetchall():
                self._refresh_project_search(conn, project["id"])
        return {"tag_id": tag_id, "deleted": True}

    def update_task_tags(self, task_id: int, tags_to_add: list[str] | None = None, tags_to_remove: list[str] | None = None) -> dict:
        with connect(self.config.db_path) as conn:
            task = conn.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise ValueError(f"Task {task_id} not found.")
            for tag_name in tags_to_add or []:
                tag = self._ensure_tag(conn, tag_name)
                conn.execute("INSERT OR IGNORE INTO task_tags (task_id, tag_id) VALUES (?, ?)", (task_id, tag["id"]))
            for tag_name in tags_to_remove or []:
                normalized = normalize_tag(tag_name)
                conn.execute(
                    """
                    DELETE FROM task_tags
                    WHERE task_id = ? AND tag_id IN (SELECT id FROM tags WHERE normalized_name = ?)
                    """,
                    (task_id, normalized),
                )
            self._refresh_project_search(conn, task["project_id"])
        return self.get_task(task_id)

    def search_tasks(self, query: str, project_id: int | None = None, limit: int = 20) -> list[dict]:
        ids = self._search_ids("task", query, project_id, limit)
        if ids:
            return [self.get_task(task_id) for task_id in ids]
        return self.list_tasks(project_id=project_id, search=query)[:limit]

    def search_work_units(self, query: str, project_id: int | None = None, limit: int = 20) -> list[dict]:
        ids = self._search_ids("work_unit", query, project_id, limit)
        if ids:
            return [self.get_work_unit(work_unit_id) for work_unit_id in ids]
        return self.list_work_units(project_id=project_id, search=query)[:limit]

    def _default_template_id(self, conn) -> int:
        row = conn.execute("SELECT id FROM project_templates WHERE name = ?", ("Default",)).fetchone()
        if row is None:
            raise ValueError("Default template is missing.")
        return int(row["id"])

    def _seed_project_statuses(self, conn, project_id: int, template_id: int) -> dict[str, int]:
        statuses = conn.execute(
            "SELECT * FROM template_statuses WHERE template_id = ? ORDER BY position",
            (template_id,),
        ).fetchall()
        status_id_by_key: dict[str, int] = {}
        for status in statuses:
            cursor = conn.execute(
                """
                INSERT INTO project_statuses
                (project_id, key, name, position, is_started, is_blocked, is_terminal, is_reopened)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    status["key"],
                    status["name"],
                    status["position"],
                    status["is_started"],
                    status["is_blocked"],
                    status["is_terminal"],
                    status["is_reopened"],
                ),
            )
            status_id_by_key[status["key"]] = int(cursor.lastrowid)
        return status_id_by_key

    def _seed_project_tasks(self, conn, project_id: int, template_id: int, status_id_by_key: dict[str, int]) -> None:
        tasks = conn.execute(
            "SELECT * FROM template_tasks WHERE template_id = ? ORDER BY position",
            (template_id,),
        ).fetchall()
        for task in tasks:
            conn.execute(
                """
                INSERT INTO tasks (project_id, status_id, title, description, priority, position)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    status_id_by_key.get(task["status_key"], status_id_by_key["todo"]),
                    task["title"],
                    task["description"],
                    task["priority"],
                    task["position"],
                ),
            )

    def _status_id(self, conn, project_id: int, status: str) -> int:
        row = conn.execute(
            """
            SELECT id FROM project_statuses
            WHERE project_id = ? AND (LOWER(name) = ? OR key = ?)
            """,
            (project_id, status.lower(), normalize_status_key(status)),
        ).fetchone()
        if row is None:
            raise ValueError(f"Status {status!r} not found in project {project_id}.")
        return int(row["id"])

    def _next_task_position(self, conn, project_id: int, status_id: int) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next_position FROM tasks WHERE project_id = ? AND status_id = ?",
            (project_id, status_id),
        ).fetchone()
        return int(row["next_position"])

    def _update_row(self, table: str, row_id: int, updates: dict[str, Any]) -> None:
        with connect(self.config.db_path) as conn:
            self._update_row_with_conn(conn, table, row_id, updates)

    def _update_row_with_conn(self, conn, table: str, row_id: int, updates: dict[str, Any]) -> None:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values())
        values.append(row_id)
        conn.execute(
            f"UPDATE {table} SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )

    def _ensure_tag(self, conn, name: str) -> dict:
        display = name.strip()
        normalized = normalize_tag(display)
        if not normalized:
            raise ValueError("Tag name cannot be empty.")
        conn.execute(
            "INSERT OR IGNORE INTO tags (name, normalized_name) VALUES (?, ?)",
            (display, normalized),
        )
        row = conn.execute("SELECT * FROM tags WHERE normalized_name = ?", (normalized,)).fetchone()
        return dict(row)

    def _set_tags(self, conn, entity_type: str, entity_id: int, tags: list[str]) -> None:
        if entity_type == "task":
            table, id_column = "task_tags", "task_id"
        elif entity_type == "work_unit":
            table, id_column = "work_unit_tags", "work_unit_id"
        else:
            raise ValueError(f"Unsupported tag entity type {entity_type!r}.")
        conn.execute(f"DELETE FROM {table} WHERE {id_column} = ?", (entity_id,))
        for tag_name in tags:
            tag = self._ensure_tag(conn, tag_name)
            conn.execute(
                f"INSERT OR IGNORE INTO {table} ({id_column}, tag_id) VALUES (?, ?)",
                (entity_id, tag["id"]),
            )

    def _tags_for(self, conn, entity_type: str, entity_id: int) -> list[str]:
        if entity_type == "task":
            table, id_column = "task_tags", "task_id"
        elif entity_type == "work_unit":
            table, id_column = "work_unit_tags", "work_unit_id"
        else:
            raise ValueError(f"Unsupported tag entity type {entity_type!r}.")
        return [
            row["name"]
            for row in conn.execute(
                f"""
                SELECT tags.name
                FROM tags
                JOIN {table} ON {table}.tag_id = tags.id
                WHERE {table}.{id_column} = ?
                ORDER BY tags.normalized_name
                """,
                (entity_id,),
            ).fetchall()
        ]

    def _decorate_task(self, conn, row) -> dict:
        result = dict(row)
        result["tags"] = self._tags_for(conn, "task", row["id"])
        return result

    def _decorate_work_unit(self, conn, row) -> dict:
        result = dict(row)
        result["tags"] = self._tags_for(conn, "work_unit", row["id"])
        return result

    def _fts_available(self, conn) -> bool:
        row = conn.execute("SELECT value FROM search_meta WHERE key = 'fts5_available'").fetchone()
        return bool(row and row["value"] == "1")

    def _refresh_project_search(self, conn, project_id: int) -> None:
        if not self._fts_available(conn):
            return
        conn.execute("DELETE FROM search_index WHERE project_id = ?", (project_id,))
        task_rows = conn.execute(
            """
            SELECT t.id, t.title, COALESCE(t.description, '') AS description, COALESCE(t.helpdesk_ref_id, '') AS helpdesk_ref_id
            FROM tasks t
            WHERE t.project_id = ?
            """,
            (project_id,),
        ).fetchall()
        for task in task_rows:
            comments = " ".join(
                row["content"]
                for row in conn.execute("SELECT content FROM task_comments WHERE task_id = ?", (task["id"],)).fetchall()
            )
            tags = " ".join(self._tags_for(conn, "task", task["id"]))
            conn.execute(
                """
                INSERT INTO search_index (entity_type, entity_id, project_id, title, body, tags, helpdesk_ref_id)
                VALUES ('task', ?, ?, ?, ?, ?, ?)
                """,
                (task["id"], project_id, task["title"], f"{task['description']} {comments}", tags, task["helpdesk_ref_id"]),
            )
        work_unit_rows = conn.execute(
            """
            SELECT id, title, COALESCE(description, '') AS description
            FROM work_units
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchall()
        for work_unit in work_unit_rows:
            tags = " ".join(self._tags_for(conn, "work_unit", work_unit["id"]))
            conn.execute(
                """
                INSERT INTO search_index (entity_type, entity_id, project_id, title, body, tags, helpdesk_ref_id)
                VALUES ('work_unit', ?, ?, ?, ?, ?, '')
                """,
                (work_unit["id"], project_id, work_unit["title"], work_unit["description"], tags),
            )

    def _search_ids(self, entity_type: str, query: str, project_id: int | None, limit: int) -> list[int]:
        with connect(self.config.db_path) as conn:
            if not self._fts_available(conn):
                return []
            clauses = ["entity_type = ?", "search_index MATCH ?"]
            params: list[Any] = [entity_type, query]
            if project_id is not None:
                clauses.append("project_id = ?")
                params.append(project_id)
            params.append(limit)
            try:
                return [
                    int(row["entity_id"])
                    for row in conn.execute(
                        f"""
                        SELECT entity_id
                        FROM search_index
                        WHERE {' AND '.join(clauses)}
                        ORDER BY rank
                        LIMIT ?
                        """,
                        params,
                    ).fetchall()
                ]
            except sqlite3.OperationalError:
                return []

