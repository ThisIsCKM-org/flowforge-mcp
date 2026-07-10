# FlowForge MCP

FlowForge MCP is a local-first task-management MCP server for projects, Work Units, tasks, tags, comments, keyword search, and external helpdesk references.

A **Work Unit** is a user-visible feature, milestone, deliverable, or initiative. It groups related tasks so humans and AI agents can discuss progress at the level of meaningful outcomes instead of individual chores.

## Features

- Projects with template-seeded statuses
- Built-in workflow: Planning, Todo, In Progress, Review, Done, Blocked, Reopened
- Work Units for features, milestones, deliverables, and initiatives
- Tasks that can belong to a Work Unit or stand alone directly under a project
- Tags with case-insensitive normalization
- Comments on tasks
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

## Run

```bash
uv run flowforge-mcp
```

or:

```bash
python3 server.py
```

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

## Branch Model

- `develop` is the default active development branch.
- `main` is the stable/release branch.
- Feature branches should branch from `develop` and merge back into `develop`.
- Release-ready changes merge from `develop` into `main`.

## Future Direction

FlowForge is MCP-first in v1. The service layer is kept separate from MCP wrappers so a future SaaS web interface and Agent AI planning assistant can reuse the same project/task backend.
