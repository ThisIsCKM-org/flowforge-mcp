import sqlite3


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
