# FlowForge MCP Tools Reference

## Conventions

- Tools prefer project, work unit, and task keys over numeric IDs.
- Many read tools accept `include_ids` to reveal internal IDs when needed.
- Search and list tools are designed to work with keys and human-readable filters.

## Project Tools

- `list_templates`
- `create_project_template`
- `create_project`
- `list_projects`
- `get_project`
- `update_project`
- `list_project_statuses`

## Work Unit Tools

- `create_work_unit`
- `list_work_units`
- `search_work_units`
- `get_work_unit`
- `update_work_unit`
- `get_work_unit_progress`

## Task Tools

- `create_task`
- `list_tasks`
- `search_tasks`
- `get_task`
- `get_task_by_helpdesk_ref`
- `get_task_display`
- `update_task`
- `delete_task`
- `reorder_tasks`

## Comment Tools

- `create_task_comment`
- `list_task_comments`
- `update_task_comment`
- `delete_task_comment`

## Attachment Tools

- `add_task_image_attachment`
- `list_task_image_attachments`
- `add_comment_image_attachment`
- `list_comment_image_attachments`
- `get_image_attachment`
- `delete_image_attachment`

The attachment tools store bytes in SQLite and expose metadata by default. `get_task_display` is the user-friendly path when a caller wants rendered markdown with exported local image files.

## Tag Tools

- `list_tags`
- `create_tag`
- `rename_tag`
- `delete_tag`
- `update_task_tags`

## Practical Usage Notes

- Use `create_project` first so the project gets workflow statuses seeded from a template.
- Use `create_work_unit` when a set of tasks represents a meaningful delivery unit.
- Use `search_tasks` or `search_work_units` when the user has only partial context.
- Use `get_task_display` for presentation, not raw task inspection.
- Use `get_task_by_helpdesk_ref` when syncing with an external support system.
