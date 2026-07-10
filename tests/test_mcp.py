from flowforge.mcp_server import SERVER_DESCRIPTION, create_mcp


def test_server_description_mentions_work_units():
    assert "Work Units" in SERVER_DESCRIPTION
    assert "helpdesk-reference" in SERVER_DESCRIPTION


def test_create_mcp_smoke():
    mcp = create_mcp()
    assert mcp is not None
