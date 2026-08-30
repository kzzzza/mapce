from mapce.mcp.protocol import to_mcp_result
from mapce.mcp.tools import TOOL_DEFINITIONS


def test_all_tools_publish_output_schemas():
    assert len(TOOL_DEFINITIONS) == 11
    assert all(tool.outputSchema is not None for tool in TOOL_DEFINITIONS)


def test_mcp_result_has_structured_and_text_fallback():
    payload = {"status": "ok", "paper_id": "paper-one"}

    result = to_mcp_result(payload)

    assert result.structuredContent == payload
    assert '"paper_id": "paper-one"' in result.content[0].text
    assert result.isError is False


def test_mcp_error_sets_is_error_without_losing_json_fallback():
    payload = {"status": "error", "error_code": "paper_not_found", "message": "missing"}

    result = to_mcp_result(payload)

    assert result.structuredContent == payload
    assert result.isError is True
    assert '"error_code": "paper_not_found"' in result.content[0].text
