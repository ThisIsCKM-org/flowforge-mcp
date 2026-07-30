from __future__ import annotations

import os

from flowforge.mcp_server import create_mcp, main


def _create_vercel_app():
    # Vercel Python functions look for a top-level ASGI app export.
    # Keep this separate from the CLI entrypoint so stdio usage still works.
    return create_mcp().http_app(
        path=os.environ.get("FLOWFORGE_HTTP_PATH", "/mcp"),
        transport="streamable-http",
    )


app = _create_vercel_app()
application = app


if __name__ == "__main__":
    main()
