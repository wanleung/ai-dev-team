"""Tests for Orchestrator MCP wiring (mcp_servers → tool_registry injection)."""
from unittest.mock import MagicMock, patch

from tools import builtin_tools, CombinedToolRegistry


class TestOrchestratorMCPWiring:
    """Test that Orchestrator correctly wires MCP servers to tool_registry for agents."""

    def test_orchestrator_uses_builtin_tools_when_no_mcp_servers(self):
        """Default construction (no mcp_servers) uses builtin_tools for both agents."""
        from orchestrator import Orchestrator

        orch = Orchestrator(model="gpt-4.1")
        assert orch.reviewer._tool_registry is builtin_tools
        assert orch.qa_planner._tool_registry is builtin_tools

    def test_orchestrator_uses_builtin_tools_when_mcp_servers_is_empty_list(self):
        """Empty mcp_servers list uses builtin_tools (no MCP overhead)."""
        from orchestrator import Orchestrator

        orch = Orchestrator(model="gpt-4.1", mcp_servers=[])
        assert orch.reviewer._tool_registry is builtin_tools
        assert orch.qa_planner._tool_registry is builtin_tools

    def test_orchestrator_wires_combined_registry_when_mcp_servers_given(self):
        """When mcp_servers provided, CombinedToolRegistry is built and injected."""
        from orchestrator import Orchestrator

        servers = [{"name": "s", "type": "stdio", "command": "npx", "args": []}]
        mock_mcp = MagicMock()
        mock_combined = MagicMock(spec=CombinedToolRegistry)
        with patch("orchestrator.MCPToolRegistry", return_value=mock_mcp) as MockMCP, \
             patch("orchestrator.CombinedToolRegistry", return_value=mock_combined) as MockCombined:
            orch = Orchestrator(model="gpt-4.1", mcp_servers=servers)
            MockMCP.assert_called_once_with(servers)
            MockCombined.assert_called_once_with(builtin_tools, mock_mcp)
            assert orch.reviewer._tool_registry is mock_combined
            assert orch.qa_planner._tool_registry is mock_combined

    def test_news_reviewer_gets_google_and_playwright_mcp_servers(self):
        """News reviewer source tools include search and rendered-browser MCP."""
        from orchestrator import Orchestrator

        google = {"name": "google_search", "type": "http", "url": "http://search/mcp"}
        playwright = {
            "name": "playwright",
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@playwright/mcp@latest", "--headless"],
        }
        rag = {"name": "rag", "type": "http", "url": "http://rag/mcp"}
        servers = [google, playwright, rag]

        combined_mcp = MagicMock()
        rag_mcp = MagicMock()
        source_mcp = MagicMock()
        with patch(
            "orchestrator.MCPToolRegistry",
            side_effect=[combined_mcp, rag_mcp, source_mcp],
        ) as MockMCP, patch("orchestrator.CombinedToolRegistry", return_value=MagicMock()):
            orch = Orchestrator(model="gpt-4.1", mcp_servers=servers)

        assert MockMCP.call_args_list[2].args[0] == [google, playwright]
        assert orch.news_reviewer._tool_registry is source_mcp
