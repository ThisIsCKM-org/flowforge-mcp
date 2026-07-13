# FlowForge MCP Project Analysis

## Overview

FlowForge MCP is a local-first task management backend exposed as an MCP server. It is designed for both humans and AI agents to manage:

- Projects
- Work Units
- Tasks
- Tags
- Task comments
- Image attachments on tasks and comments
- Keyword search
- External helpdesk references

The defining idea of the project is the **Work Unit**: a user-visible container for meaningful delivery chunks such as features, milestones, deliverables, or initiatives. Tasks can either belong to a Work Unit or live directly under a project.

## What The Project Is Built For

This repository is not a general-purpose web app. It is an MCP-first service that provides a structured task model for agent workflows and local automation.

Good fits for this project:

- Managing product delivery work in a structured way
- Tracking progress at a higher level than raw tasks
- Using deterministic keys for agent-friendly references
- Storing task context, screenshots, and discussion in one place
- Running locally over stdio or over a private HTTP transport

## Architecture

The codebase is intentionally small and split into a few clear layers:

- `flowforge/service.py` contains the business logic and SQLite operations.
- `flowforge/mcp_server.py` exposes the service through MCP tools.
- `flowforge/db/schema.py` defines schema creation, migrations, key generation, and search setup.
- `flowforge/config.py` handles runtime configuration from environment variables.
- `flowforge/models.py` defines Pydantic request models.
- `flowforge/db/connection.py` wraps SQLite connection setup.

This separation is a good sign: the service layer can be reused outside MCP later, which matches the README’s stated future direction.

## Data Model

The SQLite schema centers on a few core entities:

- `project_templates`
- `projects`
- `project_statuses`
- `work_units`
- `tasks`
- `task_comments`
- `image_attachments`
- `tags`
- `task_tags`
- `work_unit_tags`

Important behaviors:

- Projects can be seeded from templates.
- Every project gets a workflow status set, defaulting to:
  - Planning
  - Todo
  - In Progress
  - Review
  - Done
  - Blocked
  - Reopened
- Work Units carry a type such as `feature`, `milestone`, `deliverable`, or `initiative`.
- Tasks may be scoped to a Work Unit or remain standalone within a project.
- Tags are normalized case-insensitively.
- Image attachments are stored as SQLite BLOBs and can belong to either a task or a comment.
- Tasks may carry an optional `helpdesk_ref_id`, with uniqueness enforced per project.

## Key System

The project uses human-readable keys instead of relying on numeric IDs in normal usage.

Observed patterns:

- Project keys are unique globally.
- Work Unit keys are unique within a project.
- Task keys are unique within a project.
- Keys can be generated automatically from names.
- Task keys are derived from the project key or the Work Unit key, producing values like `FLOW-1` or `FM1-2`.

This is very MCP-friendly because agents can refer to stable semantic keys rather than internal IDs.

## Search

Search is backed by SQLite FTS5 when available, with a LIKE fallback when it is not.

Search covers:

- Task titles and descriptions
- Work Unit titles and descriptions
- Tags
- Helpdesk reference IDs
- Comments

That makes the system useful as a lightweight context store, not just a list of tasks.

## MCP Surface

The MCP server is implemented with `FastMCP` and supports both stdio and HTTP-style transports.

The public tool surface includes:

- Template management
- Project create/read/update/list
- Work Unit create/read/update/list/search/progress
- Task create/read/update/delete/list/search/reorder
- Task comments
- Image attachments for tasks and comments
- Tag management
- Task tag updates
- Task rendering into markdown with exported attachment files

The server also hides internal numeric IDs by default and prefers keys in tool signatures. That is a strong design choice for agent usability.

## Runtime And Storage

Storage defaults to a local SQLite file:

- Default path: `data/flowforge.db`
- Override with `FLOWFORGE_DB_PATH`

Other runtime settings:

- `FLOWFORGE_MAX_IMAGE_BYTES` controls the attachment size limit
- `FLOWFORGE_ATTACHMENT_EXPORT_DIR` controls where rendered task images are exported

The connection layer enables foreign keys and creates directories as needed. The service initialization also creates the schema automatically.

## Entry Points

Main startup options:

- `uv run flowforge-mcp`
- `uv run flowforge-mcp streamable-http --host 127.0.0.1 --port 8765 --path /mcp`
- `python3 server.py`

There is also a documented Codex MCP registration command in the README.

## Testing Signals

The tests show the intended behavior clearly:

- Default template seeding is expected.
- Project creation automatically seeds statuses.
- Generated keys must be deterministic and unique.
- Legacy databases without key columns should migrate cleanly.
- Tags should normalize idempotently.
- Helpdesk references are project-scoped.
- Search should work with both FTS5 and the fallback path.
- Multiple attachments on tasks and comments are supported.

That test coverage is a positive signal that the repo already protects its core behaviors.

## Strengths

- Clear service/MCP separation
- Human-readable key system
- Local-first and offline-friendly by default
- Good support for rich task context through comments and images
- Migration logic for older databases
- Search fallback when FTS5 is unavailable

## Risks And Gaps

- The project is SQLite-centric, so concurrency and multi-user scaling will be limited without extra coordination.
- Image attachments are stored in the database, which simplifies portability but can make large databases grow quickly.
- The project currently focuses on a local MCP backend, so there is no built-in web UI or access control layer.
- HTTP transport guidance recommends external authentication or reverse proxy protection before wider exposure.

## Overall Assessment

FlowForge MCP is a well-scoped agent-friendly task backend with a strong emphasis on structured work tracking, searchable context, and readable identifiers. It looks like a solid foundation for a future SaaS or web interface because the business logic is already isolated from the MCP transport layer.
