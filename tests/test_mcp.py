import pytest

from flowforge.mcp_server import SERVER_DESCRIPTION, create_mcp, parse_args


def test_server_description_mentions_work_units():
    assert "Work Units" in SERVER_DESCRIPTION
    assert "helpdesk-reference" in SERVER_DESCRIPTION


@pytest.mark.anyio
async def test_create_mcp_registers_image_attachment_tools():
    mcp = create_mcp()
    tools = {tool.name for tool in await mcp.list_tools()}

    assert {
        "add_task_image_attachment",
        "list_task_image_attachments",
        "add_comment_image_attachment",
        "list_comment_image_attachments",
        "get_image_attachment",
        "delete_image_attachment",
        "get_task_display",
    } <= tools


@pytest.mark.anyio
async def test_key_based_tools_do_not_require_numeric_ids():
    mcp = create_mcp()
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    create_task_schema = tools["create_task"].parameters["properties"]
    get_task_schema = tools["get_task"].parameters["properties"]
    list_projects_schema = tools["list_projects"].parameters["properties"]

    assert "project_key" in create_task_schema
    assert "work_unit_key" in create_task_schema
    assert "project_id" not in create_task_schema
    assert "work_unit_id" not in create_task_schema
    assert "task_key" in get_task_schema
    assert "task_id" not in get_task_schema
    assert "include_ids" in list_projects_schema


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
