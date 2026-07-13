from __future__ import annotations

import argparse
import sys

from .config import FlowForgeConfig
from .service import FlowForgeService


SERVER_DESCRIPTION = (
    "FlowForge MCP provides local project, work-unit, task, tag, comment, "
    "attachment, keyword-search, and helpdesk-reference management for AI agents and humans. "
    "Work Units represent meaningful chunks of value such as features, milestones, "
    "deliverables, or initiatives."
)


def create_service(config: FlowForgeConfig | None = None) -> FlowForgeService:
    return FlowForgeService(config)


def create_mcp():
    try:
        from fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("fastmcp is required to run FlowForge MCP. Install dependencies first.") from exc

    service = create_service()
    mcp = FastMCP("FlowForge MCP", instructions=SERVER_DESCRIPTION)

    def compact(payload: dict) -> dict:
        return {key: value for key, value in payload.items() if value is not None}

    def without_fields(value, fields: set[str]):
        if isinstance(value, list):
            return [without_fields(item, fields) for item in value]
        if isinstance(value, dict):
            return {key: without_fields(item, fields) for key, item in value.items() if key not in fields}
        return value

    def public_entity(value, include_ids: bool = False):
        if include_ids:
            return value
        if isinstance(value, list):
            return [public_entity(item, include_ids=False) for item in value]
        if isinstance(value, dict):
            result = without_fields(value, {"project_id", "work_unit_id", "task_id"})
            result.pop("id", None)
            return result
        return value

    def public_related(value, include_ids: bool = False):
        if include_ids:
            return value
        return without_fields(value, {"project_id", "work_unit_id", "task_id"})

    def public_statuses(value, include_ids: bool = False):
        if include_ids:
            return value
        return without_fields(value, {"id", "project_id"})

    def project_id(project_key: str) -> int:
        return service.project_id_for_key(project_key)

    def work_unit_id(project_key: str, work_unit_key: str | None) -> int | None:
        if work_unit_key is None:
            return None
        return service.work_unit_id_for_key(project_key, work_unit_key)

    def task_id(task_key: str, project_key: str | None = None) -> int:
        return service.task_id_for_key(task_key, project_key)

    @mcp.tool(description="List project templates available for creating projects.")
    def list_templates() -> list[dict]:
        return service.list_templates()

    @mcp.tool(description="Create a project template with statuses and optional starter tasks.")
    def create_project_template(name: str, description: str | None = None, statuses: list[dict] | None = None, starter_tasks: list[dict] | None = None) -> dict:
        return service.create_project_template(
            {
                "name": name,
                "description": description,
                "statuses": statuses or [],
                "starter_tasks": starter_tasks or [],
            }
        )

    @mcp.tool(description="Create a project and seed its statuses from a template. Optionally provide a human-readable unique key.")
    def create_project(name: str, key: str | None = None, description: str | None = None, template_id: int | None = None, include_ids: bool = False) -> dict:
        project = service.create_project({"name": name, "key": key, "description": description, "template_id": template_id})
        return public_entity(project, include_ids=include_ids)

    @mcp.tool(description="List projects with optional text search over key, name, and description. Numeric IDs are hidden unless include_ids is true.")
    def list_projects(search: str | None = None, include_ids: bool = False) -> list[dict]:
        return public_entity(service.list_projects(search=search), include_ids=include_ids)

    @mcp.tool(description="Get a project by key, including its statuses.")
    def get_project(project_key: str, include_ids: bool = False) -> dict:
        return public_entity(service.get_project_by_key(project_key), include_ids=include_ids)

    @mcp.tool(description="Update a project's key, name, or description by project key.")
    def update_project(project_key: str, name: str | None = None, key: str | None = None, description: str | None = None, include_ids: bool = False) -> dict:
        project = service.update_project(project_id(project_key), compact({"name": name, "key": key, "description": description}))
        return public_entity(project, include_ids=include_ids)

    @mcp.tool(description="List workflow statuses for a project key.")
    def list_project_statuses(project_key: str, include_ids: bool = False) -> list[dict]:
        return public_statuses(service.list_project_statuses(project_id(project_key)), include_ids=include_ids)

    @mcp.tool(description="Create a workflow status in a project key. The key defaults to a normalized form of the name.")
    def create_project_status(
        project_key: str,
        name: str,
        key: str | None = None,
        position: int | None = None,
        is_started: bool = False,
        is_blocked: bool = False,
        is_terminal: bool = False,
        is_reopened: bool = False,
        include_ids: bool = False,
    ) -> dict:
        status = service.create_project_status(
            {
                "project_id": project_id(project_key),
                "name": name,
                "key": key,
                "position": position,
                "is_started": is_started,
                "is_blocked": is_blocked,
                "is_terminal": is_terminal,
                "is_reopened": is_reopened,
            }
        )
        return public_statuses(status, include_ids=include_ids)

    @mcp.tool(description="Update a workflow status by name or key within a project key.")
    def update_project_status(
        project_key: str,
        status: str,
        name: str | None = None,
        key: str | None = None,
        position: int | None = None,
        is_started: bool | None = None,
        is_blocked: bool | None = None,
        is_terminal: bool | None = None,
        is_reopened: bool | None = None,
        include_ids: bool = False,
    ) -> dict:
        updated = service.update_project_status(
            project_id(project_key),
            status,
            compact(
                {
                    "name": name,
                    "key": key,
                    "position": position,
                    "is_started": is_started,
                    "is_blocked": is_blocked,
                    "is_terminal": is_terminal,
                    "is_reopened": is_reopened,
                }
            ),
        )
        return public_statuses(updated, include_ids=include_ids)

    @mcp.tool(description="Create a Work Unit in a project key. Optionally provide a Work Unit key such as FM1.")
    def create_work_unit(
        project_key: str,
        title: str,
        key: str | None = None,
        description: str | None = None,
        type: str = "feature",
        status: str | None = None,
        priority: str = "medium",
        start_date: str | None = None,
        target_date: str | None = None,
        tags: list[str] | None = None,
        include_ids: bool = False,
    ) -> dict:
        unit = service.create_work_unit(
            {
                "project_id": project_id(project_key),
                "title": title,
                "key": key,
                "description": description,
                "type": type,
                "status": status,
                "priority": priority,
                "start_date": start_date,
                "target_date": target_date,
                "tags": tags or [],
            }
        )
        return public_entity(unit, include_ids=include_ids)

    @mcp.tool(description="List Work Units with optional project key and filters. Numeric IDs are hidden unless include_ids is true.")
    def list_work_units(
        project_key: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        tag: str | None = None,
        search: str | None = None,
        include_ids: bool = False,
    ) -> list[dict]:
        resolved_project_id = project_id(project_key) if project_key is not None else None
        units = service.list_work_units(project_id=resolved_project_id, status=status, priority=priority, tag=tag, search=search)
        return public_entity(units, include_ids=include_ids)

    @mcp.tool(description="Search Work Units by keyword using local SQLite search, optionally scoped by project key.")
    def search_work_units(query: str, project_key: str | None = None, limit: int = 20, include_ids: bool = False) -> list[dict]:
        resolved_project_id = project_id(project_key) if project_key is not None else None
        return public_entity(service.search_work_units(query=query, project_id=resolved_project_id, limit=limit), include_ids=include_ids)

    @mcp.tool(description="Get a Work Unit by project key and Work Unit key.")
    def get_work_unit(project_key: str, work_unit_key: str, include_ids: bool = False) -> dict:
        return public_entity(service.get_work_unit_by_key(project_key, work_unit_key), include_ids=include_ids)

    @mcp.tool(description="Update a Work Unit by project key and Work Unit key.")
    def update_work_unit(
        project_key: str,
        work_unit_key: str,
        title: str | None = None,
        key: str | None = None,
        description: str | None = None,
        type: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        start_date: str | None = None,
        target_date: str | None = None,
        tags: list[str] | None = None,
        include_ids: bool = False,
    ) -> dict:
        unit = service.update_work_unit(
            service.work_unit_id_for_key(project_key, work_unit_key),
            compact({
                "title": title,
                "key": key,
                "description": description,
                "type": type,
                "status": status,
                "priority": priority,
                "start_date": start_date,
                "target_date": target_date,
                "tags": tags,
            }),
        )
        return public_entity(unit, include_ids=include_ids)

    @mcp.tool(description="Get calculated progress for a Work Unit by project key and Work Unit key.")
    def get_work_unit_progress(project_key: str, work_unit_key: str, include_ids: bool = False) -> dict:
        progress = service.get_work_unit_progress(service.work_unit_id_for_key(project_key, work_unit_key))
        return public_entity(progress, include_ids=include_ids)

    @mcp.tool(description="Create a task in a project key, optionally linked to a Work Unit key.")
    def create_task(
        project_key: str,
        title: str,
        key: str | None = None,
        description: str | None = None,
        work_unit_key: str | None = None,
        status: str = "Todo",
        helpdesk_ref_id: str | None = None,
        priority: str = "medium",
        assignee: str | None = None,
        due_date: str | None = None,
        position: int | None = None,
        tags: list[str] | None = None,
        include_ids: bool = False,
    ) -> dict:
        task = service.create_task(
            {
                "project_id": project_id(project_key),
                "title": title,
                "key": key,
                "description": description,
                "work_unit_id": work_unit_id(project_key, work_unit_key),
                "status": status,
                "helpdesk_ref_id": helpdesk_ref_id,
                "priority": priority,
                "assignee": assignee,
                "due_date": due_date,
                "position": position,
                "tags": tags or [],
            }
        )
        return public_entity(task, include_ids=include_ids)

    @mcp.tool(description="List tasks with optional project key, Work Unit key, and filters. Numeric IDs are hidden unless include_ids is true.")
    def list_tasks(
        project_key: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        work_unit_key: str | None = None,
        tag: str | None = None,
        helpdesk_ref_id: str | None = None,
        search: str | None = None,
        include_ids: bool = False,
    ) -> list[dict]:
        resolved_project_id = project_id(project_key) if project_key is not None else None
        resolved_work_unit_id = None
        if work_unit_key is not None:
            if project_key is None:
                raise ValueError("project_key is required when filtering by work_unit_key.")
            resolved_work_unit_id = service.work_unit_id_for_key(project_key, work_unit_key)
        tasks = service.list_tasks(
            project_id=resolved_project_id,
            status=status,
            priority=priority,
            assignee=assignee,
            work_unit_id=resolved_work_unit_id,
            tag=tag,
            helpdesk_ref_id=helpdesk_ref_id,
            search=search,
        )
        return public_entity(tasks, include_ids=include_ids)

    @mcp.tool(description="Search tasks by keyword, optionally scoped by project key.")
    def search_tasks(query: str, project_key: str | None = None, limit: int = 20, include_ids: bool = False) -> list[dict]:
        resolved_project_id = project_id(project_key) if project_key is not None else None
        return public_entity(service.search_tasks(query=query, project_id=resolved_project_id, limit=limit), include_ids=include_ids)

    @mcp.tool(description="Get a task by task key. Provide project_key if the task key is not globally unique.")
    def get_task(task_key: str, project_key: str | None = None, include_ids: bool = False) -> dict:
        return public_entity(service.get_task_by_key(task_key, project_key), include_ids=include_ids)

    @mcp.tool(description="Find a task by external helpdesk reference ID within a project key.")
    def get_task_by_helpdesk_ref(project_key: str, helpdesk_ref_id: str, include_ids: bool = False) -> dict:
        task = service.get_task_by_helpdesk_ref(project_id(project_key), helpdesk_ref_id)
        return public_entity(task, include_ids=include_ids)

    @mcp.tool(description="Render a task key as user-friendly markdown with exported attachments rendered as local file links or image previews.")
    def get_task_display(task_key: str, project_key: str | None = None, include_ids: bool = False) -> dict:
        task_numeric_id = task_id(task_key, project_key)
        display = service.get_task_display(task_numeric_id)
        if include_ids:
            return display
        task = service.get_task(task_numeric_id)
        return {"task_key": task["key"], "markdown": display["markdown"], "exported_attachments": display["exported_attachments"]}

    @mcp.tool(description="Update a task by task key. Provide project_key if the task key is not globally unique.")
    def update_task(
        task_key: str,
        project_key: str | None = None,
        title: str | None = None,
        key: str | None = None,
        description: str | None = None,
        work_unit_key: str | None = None,
        status: str | None = None,
        helpdesk_ref_id: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        due_date: str | None = None,
        position: int | None = None,
        tags: list[str] | None = None,
        include_ids: bool = False,
    ) -> dict:
        resolved_task_id = task_id(task_key, project_key)
        task = service.get_task(resolved_task_id)
        resolved_work_unit_id = None
        if work_unit_key is not None:
            if project_key is None:
                project_key = service.get_project(task["project_id"])["key"]
            resolved_work_unit_id = service.work_unit_id_for_key(project_key, work_unit_key)
        updated = service.update_task(
            resolved_task_id,
            compact({
                "title": title,
                "key": key,
                "description": description,
                "work_unit_id": resolved_work_unit_id,
                "status": status,
                "helpdesk_ref_id": helpdesk_ref_id,
                "priority": priority,
                "assignee": assignee,
                "due_date": due_date,
                "position": position,
                "tags": tags,
            }),
        )
        return public_entity(updated, include_ids=include_ids)

    @mcp.tool(description="Delete a task by task key. Provide project_key if the task key is not globally unique.")
    def delete_task(task_key: str, project_key: str | None = None) -> dict:
        task = service.get_task(task_id(task_key, project_key))
        service.delete_task(task["id"])
        return {"task_key": task["key"], "deleted": True}

    @mcp.tool(description="Reorder tasks inside a status column by task keys, optionally scoped to a project key.")
    def reorder_tasks(status: str, task_keys: list[str], project_key: str | None = None, include_ids: bool = False) -> dict:
        task_ids = [task_id(key, project_key) for key in task_keys]
        resolved_project_id = project_id(project_key) if project_key is not None else None
        service.reorder_tasks(status=status, task_ids=task_ids, project_id=resolved_project_id)
        result = {"status": status, "task_keys": task_keys, "reordered": True}
        if include_ids:
            result["task_ids"] = task_ids
        return result

    @mcp.tool(description="Create a comment on a task key.")
    def create_task_comment(task_key: str, content: str, author: str | None = None, project_key: str | None = None, include_ids: bool = False) -> dict:
        comment = service.create_task_comment({"task_id": task_id(task_key, project_key), "content": content, "author": author})
        return public_related(comment, include_ids=include_ids)

    @mcp.tool(description="List comments for a task key.")
    def list_task_comments(task_key: str, project_key: str | None = None, include_ids: bool = False) -> list[dict]:
        return public_related(service.list_task_comments(task_id(task_key, project_key)), include_ids=include_ids)

    @mcp.tool(description="Update a task comment.")
    def update_task_comment(comment_id: int, content: str) -> dict:
        return service.update_task_comment(comment_id, {"content": content})

    @mcp.tool(description="Delete a task comment.")
    def delete_task_comment(comment_id: int) -> dict:
        return service.delete_task_comment(comment_id)

    @mcp.tool(description="Attach a file to a task key. Accepts base64 file data and stores it as a SQLite BLOB.")
    def add_task_attachment(
        task_key: str,
        filename: str,
        content_type: str,
        data_base64: str,
        alt_text: str | None = None,
        project_key: str | None = None,
        include_ids: bool = False,
    ) -> dict:
        attachment = service.add_task_attachment(
            task_id=task_id(task_key, project_key),
            filename=filename,
            content_type=content_type,
            data_base64=data_base64,
            alt_text=alt_text,
        )
        return public_related(attachment, include_ids=include_ids)

    @mcp.tool(description="List task attachment metadata for a task key without file bytes.")
    def list_task_attachments(task_key: str, project_key: str | None = None, include_ids: bool = False) -> list[dict]:
        return public_related(service.list_task_attachments(task_id(task_key, project_key)), include_ids=include_ids)

    @mcp.tool(description="Attach a file to a task comment. Accepts base64 file data and stores it as a SQLite BLOB.")
    def add_comment_attachment(
        comment_id: int,
        filename: str,
        content_type: str,
        data_base64: str,
        alt_text: str | None = None,
    ) -> dict:
        return service.add_comment_attachment(
            comment_id=comment_id,
            filename=filename,
            content_type=content_type,
            data_base64=data_base64,
            alt_text=alt_text,
        )

    @mcp.tool(description="List task comment attachment metadata without file bytes.")
    def list_comment_attachments(comment_id: int) -> list[dict]:
        return service.list_comment_attachments(comment_id)

    @mcp.tool(description="Get attachment metadata, optionally including base64 file data.")
    def get_attachment(attachment_id: int, include_data: bool = False) -> dict:
        return service.get_attachment(attachment_id, include_data=include_data)

    @mcp.tool(description="Delete an attachment from a task or comment.")
    def delete_attachment(attachment_id: int) -> dict:
        return service.delete_attachment(attachment_id)

    @mcp.tool(description="Attach an image to a task key. Accepts base64 image data and stores it as a SQLite BLOB.")
    def add_task_image_attachment(
        task_key: str,
        filename: str,
        content_type: str,
        data_base64: str,
        alt_text: str | None = None,
        project_key: str | None = None,
        include_ids: bool = False,
    ) -> dict:
        return add_task_attachment(task_key, filename, content_type, data_base64, alt_text=alt_text, project_key=project_key, include_ids=include_ids)

    @mcp.tool(description="List task image attachment metadata for a task key without image bytes.")
    def list_task_image_attachments(task_key: str, project_key: str | None = None, include_ids: bool = False) -> list[dict]:
        return list_task_attachments(task_key, project_key=project_key, include_ids=include_ids)

    @mcp.tool(description="Attach an image to a task comment. Accepts base64 image data and stores it as a SQLite BLOB.")
    def add_comment_image_attachment(
        comment_id: int,
        filename: str,
        content_type: str,
        data_base64: str,
        alt_text: str | None = None,
    ) -> dict:
        return add_comment_attachment(comment_id, filename, content_type, data_base64, alt_text=alt_text)

    @mcp.tool(description="List task comment image attachment metadata without image bytes.")
    def list_comment_image_attachments(comment_id: int) -> list[dict]:
        return list_comment_attachments(comment_id)

    @mcp.tool(description="Get image attachment metadata, optionally including base64 image data.")
    def get_image_attachment(attachment_id: int, include_data: bool = False) -> dict:
        return get_attachment(attachment_id, include_data=include_data)

    @mcp.tool(description="Delete an image attachment from a task or comment.")
    def delete_image_attachment(attachment_id: int) -> dict:
        return delete_attachment(attachment_id)

    @mcp.tool(description="List tags with optional search.")
    def list_tags(search: str | None = None) -> list[dict]:
        return service.list_tags(search=search)

    @mcp.tool(description="Create a tag idempotently, returning the existing canonical tag when it already exists.")
    def create_tag(name: str) -> dict:
        return service.create_tag(name)

    @mcp.tool(description="Rename a tag.")
    def rename_tag(tag_id: int, name: str) -> dict:
        return service.rename_tag(tag_id, name)

    @mcp.tool(description="Delete a tag and remove it from tasks and Work Units.")
    def delete_tag(tag_id: int) -> dict:
        return service.delete_tag(tag_id)

    @mcp.tool(description="Bulk add and remove tags on a task key.")
    def update_task_tags(task_key: str, tags_to_add: list[str] | None = None, tags_to_remove: list[str] | None = None, project_key: str | None = None, include_ids: bool = False) -> dict:
        task = service.update_task_tags(task_id(task_key, project_key), tags_to_add=tags_to_add, tags_to_remove=tags_to_remove)
        return public_entity(task, include_ids=include_ids)

    return mcp


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="flowforge-mcp",
        description="Run the FlowForge MCP server.",
    )
    parser.add_argument(
        "transport",
        nargs="?",
        default="stdio",
        choices=["stdio", "streamable-http", "http", "sse"],
        help="Transport to use. Use streamable-http for shared office deployments.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host to bind when using an HTTP transport.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port to bind when using an HTTP transport.")
    parser.add_argument("--path", default="/mcp", help="HTTP MCP endpoint path.")
    parser.add_argument("--log-level", default=None, help="Optional server log level.")
    parser.add_argument("--allowed-host", action="append", default=[], help="Allowed Host header value for HTTP transports.")
    parser.add_argument("--allowed-origin", action="append", default=[], help="Allowed Origin header value for HTTP transports.")
    parser.add_argument("--stateless", action="store_true", help="Run HTTP transport in stateless mode.")
    return parser.parse_args(argv)


def run_server(args: argparse.Namespace) -> None:
    mcp = create_mcp()
    if args.transport == "stdio":
        if sys.stderr.isatty():
            print("FlowForge MCP running on stdio. Press Ctrl-C once to stop.", file=sys.stderr)
        mcp.run(transport="stdio", log_level=args.log_level)
        return

    mcp.run(
        transport=args.transport,
        host=args.host,
        port=args.port,
        path=args.path,
        log_level=args.log_level,
        allowed_hosts=args.allowed_host or None,
        allowed_origins=args.allowed_origin or None,
        stateless=args.stateless,
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        run_server(args)
    except KeyboardInterrupt:
        if sys.stderr.isatty():
            print("\nFlowForge MCP stopped.", file=sys.stderr)
        return

