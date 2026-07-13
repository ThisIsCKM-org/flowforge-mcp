# FlowForge MCP Architecture

## System Shape

FlowForge MCP is built as a small layered Python service:

- `flowforge/service.py` implements the domain logic and database operations.
- `flowforge/mcp_server.py` exposes that service through MCP tools.
- `flowforge/db/schema.py` creates the schema, seeds defaults, and handles migrations.
- `flowforge/config.py` loads runtime settings from environment variables.
- `flowforge/models.py` defines input validation models with Pydantic.
- `flowforge/db/connection.py` configures SQLite connections.

The main architectural strength is the clean separation between the task backend and the transport layer. That makes it easier to reuse the service later in a web UI or other integration.

## Request Flow

Typical flow:

1. An MCP client sends a tool request.
2. `mcp_server.py` resolves human-readable keys into internal IDs when needed.
3. `service.py` performs validation and persistence.
4. SQLite stores the data and any related attachments or tags.
5. The server returns a key-oriented response, usually hiding numeric IDs unless explicitly requested.

## Key Design Choices

### Human-readable keys

Projects, work units, and tasks are identified by stable keys rather than only by numeric IDs. This is a good fit for AI workflows because keys are easier to refer to in prompts, logs, and generated plans.

### Local-first storage

All persistent data lives in SQLite. That keeps setup lightweight and portable, but it also means the system is best suited to single-node or tightly controlled environments.

### Search as first-class capability

The service initializes an FTS5 search index when available, with a fallback path if it is not. Search is not an afterthought; it spans tasks, work units, tags, comments, and helpdesk references.

### Rich task context

Tasks support:

- comments
- image attachments
- tags
- external helpdesk references
- due dates and assignees

That combination makes the repo more than a checklist app. It is closer to a compact work memory for agents.

## Transport

The MCP server supports:

- `stdio` for local client integration
- `streamable-http`
- `http`
- `sse`

The README recommends keeping HTTP transports behind appropriate network controls if exposed beyond localhost.

## Initialization

On startup the service:

- ensures directories exist
- opens or creates the database
- creates tables if needed
- backfills legacy keys
- seeds the default project template
- sets up search support

That means the project is designed to self-bootstrap without a separate migration toolchain.
