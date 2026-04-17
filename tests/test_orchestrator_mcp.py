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
