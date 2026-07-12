from __future__ import annotations

import base64
import binascii
import re
import sqlite3
from pathlib import Path
from typing import Any

from .config import FlowForgeConfig
from .db.connection import connect, rows_to_dicts
from .db.schema import DEFAULT_STATUSES, default_entity_key, initialize, normalize_entity_key
from .models import (
    CreateAttachment,
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
            key = self._project_key(conn, payload.key, payload.name)
            cursor = conn.execute(
                "INSERT INTO projects (key, name, description, template_id) VALUES (?, ?, ?, ?)",
                (key, payload.name, payload.description, template_id),
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
            sql += " WHERE LOWER(key) LIKE ? OR LOWER(name) LIKE ? OR LOWER(COALESCE(description, '')) LIKE ?"
            term = f"%{search.lower()}%"
            params.extend([term, term, term])
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

    def get_project_by_key(self, project_key: str) -> dict:
        return self.get_project(self.project_id_for_key(project_key))

    def project_id_for_key(self, project_key: str) -> int:
        key = normalize_entity_key(project_key, "PROJECT")
        with connect(self.config.db_path) as conn:
            row = conn.execute("SELECT id FROM projects WHERE key = ?", (key,)).fetchone()
            if row is None:
                raise ValueError(f"Project key {key!r} not found.")
            return int(row["id"])

    def work_unit_id_for_key(self, project_key: str, work_unit_key: str) -> int:
        project_id = self.project_id_for_key(project_key)
        key = normalize_entity_key(work_unit_key, "WU")
        with connect(self.config.db_path) as conn:
            row = conn.execute(
                "SELECT id FROM work_units WHERE project_id = ? AND key = ?",
                (project_id, key),
            ).fetchone()
            if row is None:
                raise ValueError(f"Work Unit key {key!r} not found in project {project_key!r}.")
            return int(row["id"])

    def task_id_for_key(self, task_key: str, project_key: str | None = None) -> int:
        key = normalize_entity_key(task_key, "TASK")
        with connect(self.config.db_path) as conn:
            params: list[Any] = [key]
            sql = "SELECT t.id FROM tasks t"
            if project_key is not None:
                sql += " JOIN projects p ON p.id = t.project_id WHERE t.key = ? AND p.key = ?"
                params.append(normalize_entity_key(project_key, "PROJECT"))
            else:
                sql += " WHERE t.key = ?"
            rows = conn.execute(sql, params).fetchall()
            if not rows:
                scope = f" in project {project_key!r}" if project_key is not None else ""
                raise ValueError(f"Task key {key!r} not found{scope}.")
            if len(rows) > 1:
                raise ValueError(f"Task key {key!r} exists in multiple projects. Provide project_key.")
            return int(rows[0]["id"])

    def update_project(self, project_id: int, payload: UpdateProject | dict) -> dict:
        payload = UpdateProject.model_validate(payload)
        updates = payload.model_dump(exclude_unset=True)
        with connect(self.config.db_path) as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                raise ValueError(f"Project {project_id} not found.")
            if "key" in updates:
                updates["key"] = normalize_entity_key(updates["key"], default_entity_key(row["name"], "PROJECT"))
            if updates:
                self._update_row_with_conn(conn, "projects", project_id, updates)
                self._refresh_project_search(conn, project_id)
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
            key = self._work_unit_key(conn, payload.project_id, payload.key, payload.title)
            cursor = conn.execute(
                """
                INSERT INTO work_units
                (project_id, key, title, description, type, status_id, priority, start_date, target_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.project_id,
                    key,
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
            clauses.append("(LOWER(wu.key) LIKE ? OR LOWER(wu.title) LIKE ? OR LOWER(COALESCE(wu.description, '')) LIKE ?)")
            term = f"%{search.lower()}%"
            params.extend([term, term, term])
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

    def get_work_unit_by_key(self, project_key: str, work_unit_key: str) -> dict:
        return self.get_work_unit(self.work_unit_id_for_key(project_key, work_unit_key))

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
            if "key" in updates:
                updates["key"] = normalize_entity_key(updates["key"], default_entity_key(row["title"], "WU"))
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
            key = self._task_key(conn, payload.project_id, payload.work_unit_id, payload.key)
            cursor = conn.execute(
                """
                INSERT INTO tasks
                (project_id, work_unit_id, key, status_id, title, description, helpdesk_ref_id, priority, assignee, due_date, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.project_id,
                    payload.work_unit_id,
                    key,
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
            clauses.append("(LOWER(t.key) LIKE ? OR LOWER(t.title) LIKE ? OR LOWER(COALESCE(t.description, '')) LIKE ? OR LOWER(COALESCE(t.helpdesk_ref_id, '')) LIKE ?)")
            term = f"%{search.lower()}%"
            params.extend([term, term, term, term])
        sql = """
            SELECT t.*, ps.name AS status, ps.key AS status_key, wu.title AS work_unit_title, wu.key AS work_unit_key
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
                SELECT t.*, ps.name AS status, ps.key AS status_key, wu.title AS work_unit_title, wu.key AS work_unit_key
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
            attachments = self._list_attachments(conn, task_id=task_id)
            result["attachments"] = attachments
            result["image_attachments"] = attachments
            result["comments"] = self._list_task_comments(conn, task_id, include_attachments=True)
        return result

    def get_task_by_key(self, task_key: str, project_key: str | None = None) -> dict:
        return self.get_task(self.task_id_for_key(task_key, project_key))

    def get_task_display(self, task_id: int) -> dict:
        task = self.get_task(task_id)
        with connect(self.config.db_path) as conn:
            task_attachments = self._export_attachments(conn, task_id=task_id, task_id_for_path=task_id)
            comments = self._list_task_comments(conn, task_id, include_attachments=False)
            for comment in comments:
                comment["attachments"] = self._export_attachments(
                    conn,
                    comment_id=comment["id"],
                    task_id_for_path=task_id,
                )
        markdown = self._task_display_markdown(task, task_attachments, comments)
        return {"task_id": task_id, "markdown": markdown, "exported_attachments": task_attachments}

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
            if "key" in updates:
                updates["key"] = normalize_entity_key(updates["key"], default_entity_key(row["title"], "TASK"))
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
            return self._list_task_comments(conn, task_id, include_attachments=True)

    def get_task_comment(self, comment_id: int) -> dict:
        with connect(self.config.db_path) as conn:
            row = conn.execute("SELECT * FROM task_comments WHERE id = ?", (comment_id,)).fetchone()
            if row is None:
                raise ValueError(f"Comment {comment_id} not found.")
            result = dict(row)
            attachments = self._list_attachments(conn, comment_id=comment_id)
            result["attachments"] = attachments
            result["image_attachments"] = attachments
            return result

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

    def add_task_attachment(
        self,
        task_id: int,
        filename: str,
        content_type: str,
        data_base64: str,
        alt_text: str | None = None,
    ) -> dict:
        return self._create_attachment(
            {
                "task_id": task_id,
                "filename": filename,
                "content_type": content_type,
                "data_base64": data_base64,
                "alt_text": alt_text,
            }
        )

    def list_task_attachments(self, task_id: int) -> list[dict]:
        with connect(self.config.db_path) as conn:
            task = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise ValueError(f"Task {task_id} not found.")
            return self._list_attachments(conn, task_id=task_id)

    def add_comment_attachment(
        self,
        comment_id: int,
        filename: str,
        content_type: str,
        data_base64: str,
        alt_text: str | None = None,
    ) -> dict:
        return self._create_attachment(
            {
                "comment_id": comment_id,
                "filename": filename,
                "content_type": content_type,
                "data_base64": data_base64,
                "alt_text": alt_text,
            }
        )

    def list_comment_attachments(self, comment_id: int) -> list[dict]:
        with connect(self.config.db_path) as conn:
            comment = conn.execute("SELECT id FROM task_comments WHERE id = ?", (comment_id,)).fetchone()
            if comment is None:
                raise ValueError(f"Comment {comment_id} not found.")
            return self._list_attachments(conn, comment_id=comment_id)

    def get_attachment(self, attachment_id: int, include_data: bool = False) -> dict:
        with connect(self.config.db_path) as conn:
            row = conn.execute("SELECT * FROM image_attachments WHERE id = ?", (attachment_id,)).fetchone()
            if row is None:
                raise ValueError(f"Attachment {attachment_id} not found.")
            return self._format_attachment(row, include_data=include_data)

    def delete_attachment(self, attachment_id: int) -> dict:
        with connect(self.config.db_path) as conn:
            row = conn.execute("SELECT id FROM image_attachments WHERE id = ?", (attachment_id,)).fetchone()
            if row is None:
                raise ValueError(f"Attachment {attachment_id} not found.")
            conn.execute("DELETE FROM image_attachments WHERE id = ?", (attachment_id,))
        return {"attachment_id": attachment_id, "deleted": True}

    def add_task_image_attachment(self, task_id: int, filename: str, content_type: str, data_base64: str, alt_text: str | None = None) -> dict:
        return self.add_task_attachment(task_id, filename, content_type, data_base64, alt_text)

    def list_task_image_attachments(self, task_id: int) -> list[dict]:
        return self.list_task_attachments(task_id)

    def add_comment_image_attachment(self, comment_id: int, filename: str, content_type: str, data_base64: str, alt_text: str | None = None) -> dict:
        return self.add_comment_attachment(comment_id, filename, content_type, data_base64, alt_text)

    def list_comment_image_attachments(self, comment_id: int) -> list[dict]:
        return self.list_comment_attachments(comment_id)

    def get_image_attachment(self, attachment_id: int, include_data: bool = False) -> dict:
        return self.get_attachment(attachment_id, include_data=include_data)

    def delete_image_attachment(self, attachment_id: int) -> dict:
        return self.delete_attachment(attachment_id)

    def _create_attachment(self, payload: CreateAttachment | dict) -> dict:
        payload = CreateAttachment.model_validate(payload)
        if (payload.task_id is None) == (payload.comment_id is None):
            raise ValueError("Attachment must belong to exactly one task or comment.")
        filename = payload.filename.strip()
        if not filename:
            raise ValueError("Attachment filename cannot be empty.")
        content_type = payload.content_type.strip().lower()
        if not content_type:
            raise ValueError("Attachment content_type cannot be empty.")
        try:
            file_data = base64.b64decode(payload.data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Attachment data_base64 must be valid base64.") from exc
        if len(file_data) > self.config.max_image_bytes:
            raise ValueError(f"Attachment exceeds maximum size of {self.config.max_image_bytes} bytes.")
        with connect(self.config.db_path) as conn:
            if payload.task_id is not None:
                owner = conn.execute("SELECT id FROM tasks WHERE id = ?", (payload.task_id,)).fetchone()
                if owner is None:
                    raise ValueError(f"Task {payload.task_id} not found.")
            if payload.comment_id is not None:
                owner = conn.execute("SELECT id FROM task_comments WHERE id = ?", (payload.comment_id,)).fetchone()
                if owner is None:
                    raise ValueError(f"Comment {payload.comment_id} not found.")
            cursor = conn.execute(
                """
                INSERT INTO image_attachments
                (task_id, comment_id, filename, content_type, image_data, size_bytes, alt_text)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.task_id,
                    payload.comment_id,
                    filename,
                    content_type,
                    file_data,
                    len(file_data),
                    payload.alt_text,
                ),
            )
            attachment_id = int(cursor.lastrowid)
        return self.get_attachment(attachment_id)

    def _create_image_attachment(self, payload: CreateAttachment | dict) -> dict:
        return self._create_attachment(payload)

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

    def _project_key(self, conn, explicit_key: str | None, name: str) -> str:
        if explicit_key:
            return normalize_entity_key(explicit_key, default_entity_key(name, "PROJECT"))
        return self._next_available_key(conn, "projects", default_entity_key(name, "PROJECT"))

    def _work_unit_key(self, conn, project_id: int, explicit_key: str | None, title: str) -> str:
        if explicit_key:
            return normalize_entity_key(explicit_key, default_entity_key(title, "WU"))
        return self._next_available_key(
            conn,
            "work_units",
            default_entity_key(title, "WU"),
            "project_id = ?",
            [project_id],
        )

    def _task_key(self, conn, project_id: int, work_unit_id: int | None, explicit_key: str | None) -> str:
        if explicit_key:
            return normalize_entity_key(explicit_key, "TASK")
        prefix_row = None
        if work_unit_id is not None:
            prefix_row = conn.execute(
                "SELECT key FROM work_units WHERE id = ? AND project_id = ?",
                (work_unit_id, project_id),
            ).fetchone()
            if prefix_row is None:
                raise ValueError(f"Work unit {work_unit_id} not found in project {project_id}.")
        else:
            prefix_row = conn.execute("SELECT key FROM projects WHERE id = ?", (project_id,)).fetchone()
            if prefix_row is None:
                raise ValueError(f"Project {project_id} not found.")
        prefix = normalize_entity_key(prefix_row["key"], "TASK")
        row = conn.execute(
            "SELECT key FROM tasks WHERE project_id = ? AND key LIKE ? ORDER BY id",
            (project_id, f"{prefix}-%"),
        ).fetchall()
        used = {item["key"] for item in row}
        sequence = 1
        while f"{prefix}-{sequence}" in used:
            sequence += 1
        return f"{prefix}-{sequence}"

    def _next_available_key(
        self,
        conn,
        table: str,
        base: str,
        extra_clause: str | None = None,
        extra_params: list[Any] | None = None,
    ) -> str:
        normalized_base = normalize_entity_key(base, "KEY")
        key = normalized_base
        suffix = 2
        while self._key_exists(conn, table, key, extra_clause, extra_params or []):
            key = f"{normalized_base}{suffix}"
            suffix += 1
        return key

    def _key_exists(
        self,
        conn,
        table: str,
        key: str,
        extra_clause: str | None = None,
        extra_params: list[Any] | None = None,
    ) -> bool:
        clauses = ["key = ?"]
        params: list[Any] = [key]
        if extra_clause:
            clauses.append(extra_clause)
            params.extend(extra_params or [])
        row = conn.execute(f"SELECT 1 FROM {table} WHERE {' AND '.join(clauses)} LIMIT 1", params).fetchone()
        return row is not None

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
                INSERT INTO tasks (project_id, key, status_id, title, description, priority, position)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    self._task_key(conn, project_id, None, None),
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

    def _list_task_comments(self, conn, task_id: int, include_attachments: bool = False) -> list[dict]:
        comments = rows_to_dicts(
            conn.execute(
                "SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at, id",
                (task_id,),
            ).fetchall()
        )
        if include_attachments:
            for comment in comments:
                attachments = self._list_attachments(conn, comment_id=comment["id"])
                comment["attachments"] = attachments
                comment["image_attachments"] = attachments
        return comments

    def _list_attachments(
        self,
        conn,
        task_id: int | None = None,
        comment_id: int | None = None,
    ) -> list[dict]:
        if (task_id is None) == (comment_id is None):
            raise ValueError("Attachment lookup needs exactly one owner.")
        owner_column = "task_id" if task_id is not None else "comment_id"
        owner_id = task_id if task_id is not None else comment_id
        return [
            self._format_attachment(row)
            for row in conn.execute(
                f"""
                SELECT *
                FROM image_attachments
                WHERE {owner_column} = ?
                ORDER BY created_at, id
                """,
                (owner_id,),
            ).fetchall()
        ]

    def _format_attachment(self, row, include_data: bool = False) -> dict:
        result = dict(row)
        file_data = result.pop("image_data")
        result["is_image"] = result["content_type"].startswith("image/")
        if include_data:
            result["data_base64"] = base64.b64encode(file_data).decode("ascii")
        return result

    def _export_attachments(
        self,
        conn,
        task_id_for_path: int,
        task_id: int | None = None,
        comment_id: int | None = None,
    ) -> list[dict]:
        if (task_id is None) == (comment_id is None):
            raise ValueError("Attachment export needs exactly one owner.")
        owner_column = "task_id" if task_id is not None else "comment_id"
        owner_id = task_id if task_id is not None else comment_id
        exported = []
        for row in conn.execute(
            f"""
            SELECT *
            FROM image_attachments
            WHERE {owner_column} = ?
            ORDER BY created_at, id
            """,
            (owner_id,),
        ).fetchall():
            metadata = self._format_attachment(row)
            export_path = self._export_attachment_file(row, task_id_for_path)
            metadata["export_path"] = str(export_path)
            exported.append(metadata)
        return exported

    def _export_attachment_file(self, row, task_id: int) -> Path:
        export_dir = self.config.attachment_export_dir / f"task-{task_id}"
        export_dir.mkdir(parents=True, exist_ok=True)
        filename = self._safe_attachment_filename(row["id"], row["filename"])
        export_path = export_dir / filename
        export_path.write_bytes(row["image_data"])
        return export_path

    def _safe_attachment_filename(self, attachment_id: int, filename: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", filename.strip()).strip(".-")
        if not normalized:
            normalized = "file"
        return f"attachment-{attachment_id}-{normalized}"

    def _task_display_markdown(self, task: dict, task_attachments: list[dict], comments: list[dict]) -> str:
        lines = [
            f"# Task {task.get('key') or '#' + str(task['id'])}: {task['title']}",
            "",
            f"- Key: {task.get('key') or 'none'}",
            f"- Work Unit: {task.get('work_unit_key') or 'none'}",
            f"- Helpdesk: {task.get('helpdesk_ref_id') or 'none'}",
            f"- Status: {task.get('status')}",
            f"- Priority: {task.get('priority')}",
            f"- Assignee: {task.get('assignee') or 'none'}",
            f"- Due date: {task.get('due_date') or 'none'}",
            f"- Tags: {', '.join(task.get('tags') or []) or 'none'}",
            "",
        ]
        if task.get("description"):
            lines.extend(["## Description", "", task["description"], ""])
        lines.extend(self._attachment_markdown("Attachments", task_attachments))
        if comments:
            lines.extend(["## Comments", ""])
            for comment in comments:
                author = comment.get("author") or "unknown"
                lines.extend([f"### Comment #{comment['id']} by {author}", "", comment["content"], ""])
                lines.extend(self._attachment_markdown("Comment attachments", comment.get("attachments") or []))
        return "\n".join(lines).rstrip() + "\n"

    def _attachment_markdown(self, title: str, attachments: list[dict]) -> list[str]:
        if not attachments:
            return []
        lines = [f"## {title}", ""]
        for attachment in attachments:
            lines.append(f"### Attachment #{attachment['id']}: {attachment['filename']}")
            lines.append("")
            if attachment.get("is_image"):
                alt_text = attachment.get("alt_text") or attachment["filename"]
                lines.append(f"![{alt_text}]({attachment['export_path']})")
            else:
                lines.append(f"[{attachment['filename']}]({attachment['export_path']})")
            lines.append("")
        return lines

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
            SELECT t.id, t.key, t.title, COALESCE(t.description, '') AS description, COALESCE(t.helpdesk_ref_id, '') AS helpdesk_ref_id
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
                (task["id"], project_id, f"{task['key']} {task['title']}", f"{task['description']} {comments}", tags, task["helpdesk_ref_id"]),
            )
        work_unit_rows = conn.execute(
            """
            SELECT id, key, title, COALESCE(description, '') AS description
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
                (work_unit["id"], project_id, f"{work_unit['key']} {work_unit['title']}", work_unit["description"], tags),
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

