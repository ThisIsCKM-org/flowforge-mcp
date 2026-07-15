# FlowForge MCP

FlowForge MCP is a local-first task-management MCP server for projects, Work Units, tasks, tags, comments, image attachments, keyword search, and external helpdesk references.

A **Work Unit** is a user-visible feature, milestone, deliverable, or initiative. It groups related tasks so humans and AI agents can discuss progress at the level of meaningful outcomes instead of individual chores.

## Features

- Projects with template-seeded statuses and human-readable unique keys
- Built-in workflow: Planning, Todo, In Progress, Review, Done, Blocked, Reopened
- Work Units for features, milestones, deliverables, and initiatives, each with a project-scoped key
- Tasks that can belong to a Work Unit or stand alone directly under a project, with generated keys like `FM1-1`
- Tags with case-insensitive normalization
- Comments on tasks
- Multiple image attachments on tasks and comments
- Optional project-scoped `helpdesk_ref_id` on tasks
- Keyword search via SQLite FTS5 with a LIKE fallback
- MCP tools over stdio using FastMCP

## Runtime Path

FlowForge stores its SQLite database locally:

```bash
export FLOWFORGE_DB_PATH=/absolute/path/to/flowforge-mcp/data/flowforge.db
```

If unset, it defaults to:

```text
data/flowforge.db
```

Image attachments are stored as SQLite BLOBs. The default limit is 10 MiB per image and can be changed with:

```bash
export FLOWFORGE_MAX_IMAGE_BYTES=10485760
```

Rendered task displays export attachment files to `/tmp/flowforge-attachments` by default. Override that path with:

```bash
export FLOWFORGE_ATTACHMENT_EXPORT_DIR=/absolute/path/to/rendered-flowforge-images
```

## Run

Local MCP clients usually launch FlowForge over stdio:

```bash
uv run flowforge-mcp
```

When run manually, the stdio server waits for MCP JSON-RPC messages on stdin. Press `Ctrl-C` once to stop it.

The top-level `server.py` entrypoint still runs the same local CLI behavior when invoked directly:

```bash
python3 server.py
```

For a shared office stack, run Streamable HTTP on a single MCP endpoint:

```bash
uv run flowforge-mcp streamable-http --host 127.0.0.1 --port 8765 --path /mcp
```

Use `--allowed-host` and `--allowed-origin` when exposing the HTTP transport behind internal infrastructure. Keep `127.0.0.1` for local testing, and put authentication/reverse-proxy controls in front before exposing it to a wider network.

## Connect Codex

```bash
codex mcp add flowforge --env FLOWFORGE_DB_PATH=/absolute/path/to/flowforge-mcp/data/flowforge.db -- uv --directory /absolute/path/to/flowforge-mcp run flowforge-mcp
```

Equivalent config:

```toml
[mcp_servers.flowforge]
command = "uv"
args = ["--directory", "/absolute/path/to/flowforge-mcp", "run", "flowforge-mcp"]
startup_timeout_sec = 20
tool_timeout_sec = 120

[mcp_servers.flowforge.env]
FLOWFORGE_DB_PATH = "/absolute/path/to/flowforge-mcp/data/flowforge.db"
```

## Unique Keys

Projects, Work Units, and tasks include user-facing keys in addition to numeric IDs. You can provide keys explicitly or let FlowForge generate them from names. For example, a project `Flowforge` can contain a Work Unit `Flowforge MCP v1` with key `FM1`; tasks under that Work Unit are generated as `FM1-1`, `FM1-2`, and so on. Standalone tasks use the project key as their prefix.

Keys are searchable through list/search tools and are included in task display markdown. MCP tools use keys for project, Work Unit, and task actions by default. Numeric project/task IDs remain internal and are hidden from list and display responses unless an MCP tool exposes an `include_ids` option and it is set to `true`.

## Image Attachments

Task and comment attachments use base64 at the MCP boundary and store bytes as SQLite BLOBs. Listing tools return metadata only; fetch bytes explicitly with `get_attachment(..., include_data=True)`. For a user-friendly task view with inline images and downloadable file links, use `get_task_display(task_key)`. It exports stored files to local paths and returns markdown with absolute image paths or links.

Attach a task file such as `.docx`, `.txt`, or `.png`:

```python
add_task_image_attachment(
    task_key="FM1-1",
    filename="before.png",
    content_type="image/png",
    data_base64="iVBORw0KGgo...",
    alt_text="Before fixing the layout",
)
add_task_image_attachment(
    task_key="FM1-1",
    filename="after.png",
    content_type="image/png",
    data_base64="iVBORw0KGgo...",
)
```

Attach a comment file such as `.docx` or `.txt`:

```python
add_comment_image_attachment(
    comment_id=17,
    filename="error-state.webp",
    content_type="image/webp",
    data_base64="UklGRiQAAABXRUJQVlA4...",
)
```

Useful attachment tools:

```python
list_task_image_attachments(task_key="FM1-1")
list_comment_image_attachments(comment_id=17)
get_image_attachment(attachment_id=5, include_data=True)
delete_image_attachment(attachment_id=5)
get_task_display(task_key="FM1-1")
```

## Branch Model

- `develop` is the default active development branch.
- `main` is the stable/release branch.
- Feature branches should branch from `develop` and merge back into `develop`.
- Release-ready changes merge from `develop` into `main`.

## Future Direction

FlowForge is MCP-first in v1. The service layer is kept separate from MCP wrappers so a future SaaS web interface and Agent AI planning assistant can reuse the same project/task backend.
