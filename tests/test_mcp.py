from flowforge.mcp_server import SERVER_DESCRIPTION, create_mcp, parse_args


def test_server_description_mentions_work_units():
    assert "Work Units" in SERVER_DESCRIPTION
    assert "helpdesk-reference" in SERVER_DESCRIPTION


def test_create_mcp_smoke():
    mcp = create_mcp()
    assert mcp is not None


def test_parse_args_defaults_to_stdio():
    args = parse_args([])

    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.path == "/mcp"


def test_parse_args_supports_streamable_http():
    args = parse_args([
        "streamable-http",
        "--host",
        "0.0.0.0",
        "--port",
        "9000",
        "--path",
        "/mcp",
        "--allowed-host",
        "flowforge.internal",
        "--allowed-origin",
        "https://office.internal",
    ])

    assert args.transport == "streamable-http"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.allowed_host == ["flowforge.internal"]
    assert args.allowed_origin == ["https://office.internal"]
