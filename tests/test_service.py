import base64
from pathlib import Path
import sqlite3

import pytest

from flowforge.config import FlowForgeConfig
from flowforge.service import FlowForgeService


def test_default_template_seeds_reopened(service):
    templates = service.list_templates()
    default = next(template for template in templates if template["name"] == "Default")
    statuses = {status["name"]: status for status in default["statuses"]}

    assert list(statuses) == ["Planning", "Todo", "In Progress", "Review", "Done", "Blocked", "Reopened"]
    assert statuses["Reopened"]["is_reopened"] == 1
    assert statuses["Done"]["is_terminal"] == 1


def test_project_creation_seeds_statuses(service):
    project = service.create_project({"name": "Launch"})
    status_names = [status["name"] for status in service.list_project_statuses(project["id"])]

    assert status_names == ["Planning", "Todo", "In Progress", "Review", "Done", "Blocked", "Reopened"]


def test_generated_keys_for_projects_work_units_and_tasks(service):
    project = service.create_project({"name": "Flowforge", "key": "FLOW"})
    unit = service.create_work_unit({"project_id": project["id"], "title": "Flowforge MCP v1", "key": "FM1"})
    first = service.create_task({"project_id": project["id"], "work_unit_id": unit["id"], "title": "Design schema"})
    second = service.create_task({"project_id": project["id"], "work_unit_id": unit["id"], "title": "Wire API"})
    standalone = service.create_task({"project_id": project["id"], "title": "Write README"})

    assert project["key"] == "FLOW"
    assert unit["key"] == "FM1"
    assert first["key"] == "FM1-1"
    assert second["key"] == "FM1-2"
    assert standalone["key"] == "FLOW-1"


def test_auto_generated_entity_keys_are_unique(service):
    first = service.create_project({"name": "Flowforge"})
    second = service.create_project({"name": "Flowforge"})
    first_unit = service.create_work_unit({"project_id": first["id"], "title": "Flowforge MCP v1"})
    second_unit = service.create_work_unit({"project_id": first["id"], "title": "Flowforge MCP v1"})

    assert first["key"] == "FLOWFORGE"
    assert second["key"] == "FLOWFORGE2"
    assert first_unit["key"] == "FM1"
    assert second_unit["key"] == "FM12"


def test_duplicate_keys_are_rejected_in_scope(service):
    project = service.create_project({"name": "Flowforge", "key": "FLOW"})
    other_project = service.create_project({"name": "Other", "key": "OTHER"})
    service.create_work_unit({"project_id": project["id"], "title": "One", "key": "FM1"})
    task = service.create_task({"project_id": project["id"], "title": "One", "key": "FM1-1"})

    with pytest.raises(sqlite3.IntegrityError):
        service.create_project({"name": "Duplicate", "key": "FLOW"})
    with pytest.raises(sqlite3.IntegrityError):
        service.create_work_unit({"project_id": project["id"], "title": "Two", "key": "FM1"})
    with pytest.raises(sqlite3.IntegrityError):
        service.create_task({"project_id": project["id"], "title": "Two", "key": "FM1-1"})

    other_task = service.create_task({"project_id": other_project["id"], "title": "Allowed", "key": "FM1-1"})
    assert other_task["key"] == task["key"]


def test_keys_are_searchable_and_rendered_in_task_display(service):
    project = service.create_project({"name": "Flowforge", "key": "FLOW"})
    unit = service.create_work_unit({"project_id": project["id"], "title": "Flowforge MCP v1", "key": "FM1"})
    task = service.create_task({"project_id": project["id"], "work_unit_id": unit["id"], "title": "Add keys"})

    assert service.list_projects(search="FLOW")[0]["id"] == project["id"]
    assert service.search_work_units("FM1", project_id=project["id"])[0]["id"] == unit["id"]
    assert service.search_tasks(task["key"], project_id=project["id"])[0]["id"] == task["id"]
    markdown = service.get_task_display(task["id"])["markdown"]
    assert f"# Task {task['key']}" in markdown
    assert f"Project: #{project['id']}" not in markdown
    assert "- Work Unit: FM1" in markdown


def test_existing_database_without_key_columns_is_backfilled(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT, template_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE project_statuses (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, key TEXT NOT NULL, name TEXT NOT NULL, position INTEGER NOT NULL, is_started INTEGER NOT NULL DEFAULT 0, is_blocked INTEGER NOT NULL DEFAULT 0, is_terminal INTEGER NOT NULL DEFAULT 0, is_reopened INTEGER NOT NULL DEFAULT 0, UNIQUE(project_id, key))")
        conn.execute("CREATE TABLE work_units (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, title TEXT NOT NULL, description TEXT, type TEXT NOT NULL DEFAULT 'feature', status_id INTEGER, priority TEXT NOT NULL DEFAULT 'medium', start_date TEXT, target_date TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, work_unit_id INTEGER, status_id INTEGER NOT NULL, title TEXT NOT NULL, description TEXT, helpdesk_ref_id TEXT, priority TEXT NOT NULL DEFAULT 'medium', assignee TEXT, due_date TEXT, position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(project_id, helpdesk_ref_id))")
        project_id = conn.execute("INSERT INTO projects (name, description) VALUES ('Flowforge', NULL)").lastrowid
        status_id = conn.execute("INSERT INTO project_statuses (project_id, key, name, position) VALUES (?, 'todo', 'Todo', 0)", (project_id,)).lastrowid
        unit_id = conn.execute("INSERT INTO work_units (project_id, title, status_id) VALUES (?, 'Flowforge MCP v1', ?)", (project_id, status_id)).lastrowid
        conn.execute("INSERT INTO tasks (project_id, work_unit_id, status_id, title) VALUES (?, ?, ?, 'Legacy task')", (project_id, unit_id, status_id))
        conn.execute("INSERT INTO tasks (project_id, status_id, title) VALUES (?, ?, 'Standalone task')", (project_id, status_id))

    migrated = FlowForgeService.for_path(db_path)
    project = migrated.list_projects()[0]
    unit = migrated.list_work_units(project_id=project["id"])[0]
    tasks = migrated.list_tasks(project_id=project["id"])

    assert project["key"] == "FLOWFORGE"
    assert unit["key"] == "FM1"
    assert {task["key"] for task in tasks} == {"FM1-1", "FLOWFORGE-1"}

def test_task_tags_helpdesk_and_lookup(service):
    project = service.create_project({"name": "Support"})
    task = service.create_task(
        {
            "project_id": project["id"],
            "title": "Fix billing webhook",
            "helpdesk_ref_id": "HD-1001",
            "tags": ["Billing", "urgent"],
        }
    )

    found = service.get_task_by_helpdesk_ref(project["id"], "HD-1001")

    assert found["id"] == task["id"]
    assert found["tags"] == ["Billing", "urgent"]


def test_duplicate_helpdesk_ref_is_rejected_per_project(service):
    project = service.create_project({"name": "Support"})
    service.create_task({"project_id": project["id"], "title": "First", "helpdesk_ref_id": "HD-7"})

    try:
        service.create_task({"project_id": project["id"], "title": "Second", "helpdesk_ref_id": "HD-7"})
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("Expected duplicate helpdesk ref to fail")


def test_same_helpdesk_ref_allowed_in_different_projects(service):
    first = service.create_project({"name": "One"})
    second = service.create_project({"name": "Two"})

    service.create_task({"project_id": first["id"], "title": "First", "helpdesk_ref_id": "HD-7"})
    task = service.create_task({"project_id": second["id"], "title": "Second", "helpdesk_ref_id": "HD-7"})

    assert task["helpdesk_ref_id"] == "HD-7"


def test_tag_normalization_is_idempotent(service):
    first = service.create_tag("Urgent")
    second = service.create_tag("urgent")
    third = service.create_tag("URGENT")

    assert first["id"] == second["id"] == third["id"]
    assert len(service.list_tags()) == 1


def test_work_unit_progress_counts_done_tasks(service):
    project = service.create_project({"name": "Commerce"})
    unit = service.create_work_unit({"project_id": project["id"], "title": "Shopping Cart Redesign"})
    todo = service.create_task({"project_id": project["id"], "work_unit_id": unit["id"], "title": "Coupon input"})
    service.create_task({"project_id": project["id"], "work_unit_id": unit["id"], "title": "Responsive mockup", "status": "Done"})

    progress = service.get_work_unit_progress(unit["id"])
    service.update_task(todo["id"], {"status": "Done"})
    finished = service.get_work_unit_progress(unit["id"])

    assert progress == {"work_unit_id": unit["id"], "total_tasks": 2, "completed_tasks": 1, "progress_percent": 50}
    assert finished["progress_percent"] == 100


def test_standalone_and_work_unit_tasks(service):
    project = service.create_project({"name": "Ops"})
    unit = service.create_work_unit({"project_id": project["id"], "title": "Database Migration"})
    grouped = service.create_task({"project_id": project["id"], "work_unit_id": unit["id"], "title": "Add migration script"})
    standalone = service.create_task({"project_id": project["id"], "title": "Update favicon"})

    assert grouped["work_unit_id"] == unit["id"]
    assert standalone["work_unit_id"] is None


def test_keyword_search_matches_comments_tags_and_helpdesk_ref(service):
    project = service.create_project({"name": "Search"})
    task = service.create_task(
        {
            "project_id": project["id"],
            "title": "Webhook failure",
            "description": "Payment event not processed",
            "helpdesk_ref_id": "HD-SEARCH",
            "tags": ["Payments"],
        }
    )
    service.create_task_comment({"task_id": task["id"], "content": "Stripe retry confirms the issue"})

    by_comment = service.search_tasks("Stripe", project_id=project["id"])
    by_tag = service.search_tasks("Payments", project_id=project["id"])
    by_ref = service.search_tasks("HD-SEARCH", project_id=project["id"])

    assert [item["id"] for item in by_comment] == [task["id"]]
    assert [item["id"] for item in by_tag] == [task["id"]]
    assert [item["id"] for item in by_ref] == [task["id"]]


def test_search_like_fallback(service):
    project = service.create_project({"name": "Fallback"})
    task = service.create_task({"project_id": project["id"], "title": "Multi word fallback search"})
    from flowforge.db.connection import connect

    with connect(service.config.db_path) as conn:
        conn.execute("UPDATE search_meta SET value = '0' WHERE key = 'fts5_available'")

    results = service.search_tasks("fallback search", project_id=project["id"])

    assert [item["id"] for item in results] == [task["id"]]

def _image_data(value: bytes = b"fake-png") -> str:
    return base64.b64encode(value).decode("ascii")


def _file_data(value: bytes = b"fake-bytes") -> str:
    return base64.b64encode(value).decode("ascii")


def test_task_file_attachments_support_non_images(service):
    project = service.create_project({"name": "Files"})
    task = service.create_task({"project_id": project["id"], "title": "Upload documents"})

    docx = service.add_task_attachment(task["id"], "brief.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", _file_data(b"docx-bytes"))
    txt = service.add_task_attachment(task["id"], "notes.txt", "text/plain", _file_data(b"txt-bytes"))
    fetched = service.get_task(task["id"])
    listed = service.list_task_attachments(task["id"])

    assert [attachment["filename"] for attachment in listed] == ["brief.docx", "notes.txt"]
    assert docx["content_type"].startswith("application/")
    assert txt["content_type"] == "text/plain"
    assert docx["size_bytes"] == len(b"docx-bytes")
    assert txt["size_bytes"] == len(b"txt-bytes")
    assert fetched["attachments"][0]["filename"] == "brief.docx"
    assert fetched["attachments"][1]["filename"] == "notes.txt"
    assert all(attachment["is_image"] is False for attachment in fetched["attachments"])


def test_get_task_display_renders_non_images_as_links(service):
    project = service.create_project({"name": "Display Files"})
    task = service.create_task({"project_id": project["id"], "title": "Read attachment"})
    comment = service.create_task_comment({"task_id": task["id"], "content": "See attached specs"})

    service.add_task_attachment(task["id"], "spec.pdf", "application/pdf", _file_data(b"pdf-bytes"))
    service.add_comment_attachment(comment["id"], "notes.csv", "text/csv", _file_data(b"csv-bytes"))

    display = service.get_task_display(task["id"])
    markdown = display["markdown"]

    assert "[spec.pdf](" in markdown
    assert "[notes.csv](" in markdown
    assert "![](" not in markdown
    assert len(display["exported_attachments"]) == 1
def test_task_image_attachments_support_multiple_images(service):
    project = service.create_project({"name": "Images"})
    task = service.create_task({"project_id": project["id"], "title": "Add screenshots"})

    first = service.add_task_image_attachment(task["id"], "before.png", "image/png", _image_data(b"before"), "Before state")
    second = service.add_task_image_attachment(task["id"], "after.jpg", "image/jpeg", _image_data(b"after"))
    attachments = service.list_task_image_attachments(task["id"])

    assert [attachment["id"] for attachment in attachments] == [first["id"], second["id"]]
    assert attachments[0]["filename"] == "before.png"
    assert attachments[0]["size_bytes"] == len(b"before")
    assert "data_base64" not in attachments[0]


def test_comment_image_attachments_support_multiple_images(service):
    project = service.create_project({"name": "Comment Images"})
    task = service.create_task({"project_id": project["id"], "title": "Review screenshot"})
    comment = service.create_task_comment({"task_id": task["id"], "content": "See these two states"})

    first = service.add_comment_image_attachment(comment["id"], "one.png", "image/png", _image_data(b"one"))
    second = service.add_comment_image_attachment(comment["id"], "two.png", "image/png", _image_data(b"two"))
    attachments = service.list_comment_image_attachments(comment["id"])

    assert [attachment["id"] for attachment in attachments] == [first["id"], second["id"]]
    assert all("data_base64" not in attachment for attachment in attachments)


def test_get_task_includes_image_attachment_metadata(service):
    project = service.create_project({"name": "Task Metadata"})
    task = service.create_task({"project_id": project["id"], "title": "Capture bug"})
    comment = service.create_task_comment({"task_id": task["id"], "content": "Screenshot attached"})
    service.add_task_image_attachment(task["id"], "task.png", "image/png", _image_data(b"task"))
    service.add_comment_image_attachment(comment["id"], "comment.png", "image/png", _image_data(b"comment"))

    fetched = service.get_task(task["id"])

    assert fetched["image_attachments"][0]["filename"] == "task.png"
    assert "data_base64" not in fetched["image_attachments"][0]
    assert fetched["comments"][0]["image_attachments"][0]["filename"] == "comment.png"
    assert "data_base64" not in fetched["comments"][0]["image_attachments"][0]


def test_get_image_attachment_can_include_base64_data(service):
    project = service.create_project({"name": "Round Trip"})
    task = service.create_task({"project_id": project["id"], "title": "Store image"})
    raw = b"image-bytes"
    attachment = service.add_task_image_attachment(task["id"], "image.webp", "image/webp", _image_data(raw))

    metadata = service.get_image_attachment(attachment["id"])
    with_data = service.get_image_attachment(attachment["id"], include_data=True)

    assert "data_base64" not in metadata
    assert base64.b64decode(with_data["data_base64"]) == raw


def test_image_attachment_validation(service, tmp_path):
    project = service.create_project({"name": "Validation"})
    task = service.create_task({"project_id": project["id"], "title": "Validate"})

    with pytest.raises(ValueError, match="valid base64"):
        service.add_task_attachment(task["id"], "broken.txt", "text/plain", "not base64")
    with pytest.raises(ValueError, match="exactly one"):
        service._create_attachment({"filename": "missing.png", "content_type": "image/png", "data_base64": _image_data()})

    limited = FlowForgeService(FlowForgeConfig(db_path=tmp_path / "limited.db", max_image_bytes=3))
    limited_project = limited.create_project({"name": "Limited"})
    limited_task = limited.create_task({"project_id": limited_project["id"], "title": "Too large"})
    with pytest.raises(ValueError, match="maximum size"):
        limited.add_task_attachment(limited_task["id"], "large.png", "image/png", _image_data(b"1234"))


def test_image_attachments_cascade_with_task_and_comment_deletes(service):
    project = service.create_project({"name": "Cascade"})
    task = service.create_task({"project_id": project["id"], "title": "Delete task"})
    comment = service.create_task_comment({"task_id": task["id"], "content": "Delete comment"})
    task_attachment = service.add_task_image_attachment(task["id"], "task.png", "image/png", _image_data(b"task"))
    comment_attachment = service.add_comment_image_attachment(comment["id"], "comment.png", "image/png", _image_data(b"comment"))

    service.delete_task_comment(comment["id"])
    assert service.list_task_image_attachments(task["id"])[0]["id"] == task_attachment["id"]
    with pytest.raises(ValueError, match="not found"):
        service.get_image_attachment(comment_attachment["id"])

    service.delete_task(task["id"])
    with pytest.raises(ValueError, match="not found"):
        service.get_image_attachment(task_attachment["id"])



def test_get_task_display_exports_attachment_files(service):
    project = service.create_project({"name": "Display"})
    task = service.create_task(
        {
            "project_id": project["id"],
            "title": "Show screenshot",
            "description": "Evidence attached",
            "tags": ["display"],
        }
    )
    comment = service.create_task_comment({"task_id": task["id"], "content": "Comment screenshot"})
    task_raw = b"task-image"
    comment_raw = b"comment-image"
    service.add_task_image_attachment(task["id"], "task screenshot.png", "image/png", _image_data(task_raw), "Task screenshot")
    service.add_comment_image_attachment(comment["id"], "comment.png", "image/png", _image_data(comment_raw), "Comment screenshot")

    display = service.get_task_display(task["id"])

    assert f"# Task {task['key']}" in display["markdown"]
    assert "![Task screenshot](" in display["markdown"]
    assert "![Comment screenshot](" in display["markdown"]
    assert len(display["exported_attachments"]) == 1
    exported_task_path = Path(display["exported_attachments"][0]["export_path"])
    assert exported_task_path.is_absolute()
    assert exported_task_path.read_bytes() == task_raw
    comment_path_text = display["markdown"].split("![Comment screenshot](", 1)[1].split(")", 1)[0]
    assert Path(comment_path_text).read_bytes() == comment_raw
