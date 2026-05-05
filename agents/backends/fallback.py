"""FallbackLLMBackend — tries backends in order, switches on connection errors."""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from agents.backends.base import LLMBackend, FALLBACK_ERRORS

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class FallbackLLMBackend(LLMBackend):
    """Ordered list of LLMBackend instances — tries each on connection failure.

    On a FALLBACK_ERRORS exception from backend N:
      - Prints a visible ⚠️ warning to stdout
      - Passes the full messages list (with history) to backend N+1
      - If all backends fail, re-raises the last exception

    Does NOT fall back on auth errors or bad-request errors — those indicate
    a configuration problem that switching backends won't fix.

    Mixed tool-capability is allowed: call_with_tools skips backends that
    return supports_tools() == False, falling through to the next capable one.
    """

    def __init__(self, backends: list[LLMBackend]) -> None:
        if not backends:
            raise ValueError("FallbackLLMBackend requires at least one backend")
        tool_support = [b.supports_tools() for b in backends]
        if len(set(tool_support)) > 1:
            non_tool = [b.model for b in backends if not b.supports_tools()]
            logger.warning(
                "FallbackLLMBackend: backends %s do not support tool-calling and will be "
                "skipped when tools are required. They will still be used for plain call().",
                non_tool,
            )
        self._backends = backends

    @property
    def model(self) -> str:
        return self._backends[0].model

    def supports_tools(self) -> bool:
        return self._backends[0].supports_tools()

    def call(self, messages: list[dict], run_id: str | None = None) -> str:
        for i, backend in enumerate(self._backends):
            try:
                return backend.call(messages)
            except FALLBACK_ERRORS as exc:
                if i < len(self._backends) - 1:
                    next_model = self._backends[i + 1].model
                    print(
                        f"⚠️  {backend.model} unreachable ({type(exc).__name__}: {exc}), "
                        f"falling back to {next_model}"
                    )
                else:
                    raise

    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
        run_id: str | None = None,
    ) -> str:
        tool_backends = [b for b in self._backends if b.supports_tools()]
        if not tool_backends:
            raise RuntimeError(
                f"No tool-capable backend available in FallbackLLMBackend "
                f"(backends: {[b.model for b in self._backends]})"
            )
        for i, backend in enumerate(tool_backends):
            try:
                return backend.call_with_tools(messages, tools, max_turns)
            except FALLBACK_ERRORS as exc:
                if i < len(tool_backends) - 1:
                    next_model = tool_backends[i + 1].model
                    print(
                        f"⚠️  {backend.model} unreachable ({type(exc).__name__}: {exc}), "
                        f"falling back to {next_model}"
                    )
                else:
                    raise
