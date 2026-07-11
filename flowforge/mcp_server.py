from __future__ import annotations

import argparse
import sys

from .config import FlowForgeConfig
from .service import FlowForgeService


SERVER_DESCRIPTION = (
    "FlowForge MCP provides local project, work-unit, task, tag, comment, "
    "image-attachment, keyword-search, and helpdesk-reference management for AI agents and humans. "
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

    @mcp.tool(description="Create a project and seed its statuses from a template.")
    def create_project(name: str, description: str | None = None, template_id: int | None = None) -> dict:
        return service.create_project({"name": name, "description": description, "template_id": template_id})

    @mcp.tool(description="List projects with optional text search over name and description.")
    def list_projects(search: str | None = None) -> list[dict]:
        return service.list_projects(search=search)

    @mcp.tool(description="Get a project by ID, including its statuses.")
    def get_project(project_id: int) -> dict:
        return service.get_project(project_id)

    @mcp.tool(description="Update a project's name or description.")
    def update_project(project_id: int, name: str | None = None, description: str | None = None) -> dict:
        return service.update_project(project_id, compact({"name": name, "description": description}))

    @mcp.tool(description="List the workflow statuses for a project, including metadata for active, blocked, terminal, and reopened states.")
    def list_project_statuses(project_id: int) -> list[dict]:
        return service.list_project_statuses(project_id)

    @mcp.tool(description="Create a Work Unit: a feature, milestone, deliverable, or initiative that groups related tasks.")
    def create_work_unit(
        project_id: int,
        title: str,
        description: str | None = None,
        type: str = "feature",
        status: str | None = None,
        priority: str = "medium",
        start_date: str | None = None,
        target_date: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        return service.create_work_unit(
            {
                "project_id": project_id,
                "title": title,
                "description": description,
                "type": type,
                "status": status,
                "priority": priority,
                "start_date": start_date,
                "target_date": target_date,
                "tags": tags or [],
            }
        )

    @mcp.tool(description="List Work Units with optional filters.")
    def list_work_units(
        project_id: int | None = None,
        status: str | None = None,
        priority: str | None = None,
        tag: str | None = None,
        search: str | None = None,
    ) -> list[dict]:
        return service.list_work_units(project_id=project_id, status=status, priority=priority, tag=tag, search=search)

    @mcp.tool(description="Search Work Units by keyword using local SQLite search.")
    def search_work_units(query: str, project_id: int | None = None, limit: int = 20) -> list[dict]:
        return service.search_work_units(query=query, project_id=project_id, limit=limit)

    @mcp.tool(description="Get a Work Unit by ID, including progress derived from child tasks.")
    def get_work_unit(work_unit_id: int) -> dict:
        return service.get_work_unit(work_unit_id)

    @mcp.tool(description="Update a Work Unit.")
    def update_work_unit(
        work_unit_id: int,
        title: str | None = None,
        description: str | None = None,
        type: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        start_date: str | None = None,
        target_date: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        return service.update_work_unit(
            work_unit_id,
            compact({
                "title": title,
                "description": description,
                "type": type,
                "status": status,
                "priority": priority,
                "start_date": start_date,
                "target_date": target_date,
                "tags": tags,
            }),
        )

    @mcp.tool(description="Get calculated progress for a Work Unit based on child task statuses.")
    def get_work_unit_progress(work_unit_id: int) -> dict:
        return service.get_work_unit_progress(work_unit_id)

    @mcp.tool(description="Create a task, optionally linked to a Work Unit, tags, and an external helpdesk reference ID.")
    def create_task(
        project_id: int,
        title: str,
        description: str | None = None,
        work_unit_id: int | None = None,
        status: str = "Todo",
        helpdesk_ref_id: str | None = None,
        priority: str = "medium",
        assignee: str | None = None,
        due_date: str | None = None,
        position: int | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        return service.create_task(
            {
                "project_id": project_id,
                "title": title,
                "description": description,
                "work_unit_id": work_unit_id,
                "status": status,
                "helpdesk_ref_id": helpdesk_ref_id,
                "priority": priority,
                "assignee": assignee,
                "due_date": due_date,
                "position": position,
                "tags": tags or [],
            }
        )

    @mcp.tool(description="List tasks with optional filters for project, status, tag, priority, assignee, Work Unit, helpdesk ref, and text.")
    def list_tasks(
        project_id: int | None = None,
        status: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        work_unit_id: int | None = None,
        tag: str | None = None,
        helpdesk_ref_id: str | None = None,
        search: str | None = None,
    ) -> list[dict]:
        return service.list_tasks(
            project_id=project_id,
            status=status,
            priority=priority,
            assignee=assignee,
            work_unit_id=work_unit_id,
            tag=tag,
            helpdesk_ref_id=helpdesk_ref_id,
            search=search,
        )

    @mcp.tool(description="Search tasks by keyword across title, description, tags, comments, Work Unit context, and helpdesk ref ID.")
    def search_tasks(query: str, project_id: int | None = None, limit: int = 20) -> list[dict]:
        return service.search_tasks(query=query, project_id=project_id, limit=limit)

    @mcp.tool(description="Get a task by ID, including tags and comments.")
    def get_task(task_id: int) -> dict:
        return service.get_task(task_id)

    @mcp.tool(description="Find a task by external helpdesk reference ID within a project.")
    def get_task_by_helpdesk_ref(project_id: int, helpdesk_ref_id: str) -> dict:
        return service.get_task_by_helpdesk_ref(project_id, helpdesk_ref_id)

    @mcp.tool(description="Render a task as user-friendly markdown with image attachments exported to local files.")
    def get_task_display(task_id: int) -> dict:
        return service.get_task_display(task_id)

    @mcp.tool(description="Update a task.")
    def update_task(
        task_id: int,
        title: str | None = None,
        description: str | None = None,
        work_unit_id: int | None = None,
        status: str | None = None,
        helpdesk_ref_id: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        due_date: str | None = None,
        position: int | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        return service.update_task(
            task_id,
            compact({
                "title": title,
                "description": description,
                "work_unit_id": work_unit_id,
                "status": status,
                "helpdesk_ref_id": helpdesk_ref_id,
                "priority": priority,
                "assignee": assignee,
                "due_date": due_date,
                "position": position,
                "tags": tags,
            }),
        )

    @mcp.tool(description="Delete a task and its comments/tag links.")
    def delete_task(task_id: int) -> dict:
        return service.delete_task(task_id)

    @mcp.tool(description="Reorder tasks inside a status column, optionally scoped to a project.")
    def reorder_tasks(status: str, task_ids: list[int], project_id: int | None = None) -> dict:
        return service.reorder_tasks(status=status, task_ids=task_ids, project_id=project_id)

    @mcp.tool(description="Create a comment on a task.")
    def create_task_comment(task_id: int, content: str, author: str | None = None) -> dict:
        return service.create_task_comment({"task_id": task_id, "content": content, "author": author})

    @mcp.tool(description="List comments for a task.")
    def list_task_comments(task_id: int) -> list[dict]:
        return service.list_task_comments(task_id)

    @mcp.tool(description="Update a task comment.")
    def update_task_comment(comment_id: int, content: str) -> dict:
        return service.update_task_comment(comment_id, {"content": content})

    @mcp.tool(description="Delete a task comment.")
    def delete_task_comment(comment_id: int) -> dict:
        return service.delete_task_comment(comment_id)

    @mcp.tool(description="Attach an image to a task. Accepts base64 image data and stores it as a SQLite BLOB.")
    def add_task_image_attachment(
        task_id: int,
        filename: str,
        content_type: str,
        data_base64: str,
        alt_text: str | None = None,
    ) -> dict:
        return service.add_task_image_attachment(
            task_id=task_id,
            filename=filename,
            content_type=content_type,
            data_base64=data_base64,
            alt_text=alt_text,
        )

    @mcp.tool(description="List task image attachment metadata without image bytes.")
    def list_task_image_attachments(task_id: int) -> list[dict]:
        return service.list_task_image_attachments(task_id)

    @mcp.tool(description="Attach an image to a task comment. Accepts base64 image data and stores it as a SQLite BLOB.")
    def add_comment_image_attachment(
        comment_id: int,
        filename: str,
        content_type: str,
        data_base64: str,
        alt_text: str | None = None,
    ) -> dict:
        return service.add_comment_image_attachment(
            comment_id=comment_id,
            filename=filename,
            content_type=content_type,
            data_base64=data_base64,
            alt_text=alt_text,
        )

    @mcp.tool(description="List task comment image attachment metadata without image bytes.")
    def list_comment_image_attachments(comment_id: int) -> list[dict]:
        return service.list_comment_image_attachments(comment_id)

    @mcp.tool(description="Get image attachment metadata, optionally including base64 image data.")
    def get_image_attachment(attachment_id: int, include_data: bool = False) -> dict:
        return service.get_image_attachment(attachment_id, include_data=include_data)

    @mcp.tool(description="Delete an image attachment from a task or comment.")
    def delete_image_attachment(attachment_id: int) -> dict:
        return service.delete_image_attachment(attachment_id)

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

    @mcp.tool(description="Bulk add and remove tags on a task.")
    def update_task_tags(task_id: int, tags_to_add: list[str] | None = None, tags_to_remove: list[str] | None = None) -> dict:
        return service.update_task_tags(task_id, tags_to_add=tags_to_add, tags_to_remove=tags_to_remove)

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

