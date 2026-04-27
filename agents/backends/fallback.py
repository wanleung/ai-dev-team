"""FallbackLLMBackend — tries backends in order, switches on connection errors."""
from __future__ import annotations
from typing import TYPE_CHECKING

from agents.backends.base import LLMBackend, FALLBACK_ERRORS

if TYPE_CHECKING:
    from tools.registry import ToolRegistry


class FallbackLLMBackend(LLMBackend):
    """Ordered list of LLMBackend instances — tries each on connection failure.

    On a FALLBACK_ERRORS exception from backend N:
      - Prints a visible ⚠️ warning to stdout
      - Passes the full messages list (with history) to backend N+1
      - If all backends fail, re-raises the last exception

    Does NOT fall back on auth errors or bad-request errors — those indicate
    a configuration problem that switching backends won't fix.
    """

    def __init__(self, backends: list[LLMBackend]) -> None:
        if not backends:
            raise ValueError("FallbackLLMBackend requires at least one backend")
        tool_support = [b.supports_tools() for b in backends]
        if len(set(tool_support)) > 1:
            raise ValueError(
                "All backends in FallbackLLMBackend must have the same supports_tools() "
                "capability. Mix of tool-capable and non-tool backends is not supported."
            )
        self._backends = backends

    @property
    def model(self) -> str:
        return self._backends[0].model

    def supports_tools(self) -> bool:
        return self._backends[0].supports_tools()

    def call(self, messages: list[dict]) -> str:
        last_exc: BaseException | None = None
        for i, backend in enumerate(self._backends):
            try:
                return backend.call(messages)
            except FALLBACK_ERRORS as exc:
                last_exc = exc
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
    ) -> str:
        last_exc: BaseException | None = None
        for i, backend in enumerate(self._backends):
            try:
                return backend.call_with_tools(messages, tools, max_turns)
            except FALLBACK_ERRORS as exc:
                last_exc = exc
                if i < len(self._backends) - 1:
                    next_model = self._backends[i + 1].model
                    print(
                        f"⚠️  {backend.model} unreachable ({type(exc).__name__}: {exc}), "
                        f"falling back to {next_model}"
                    )
                else:
                    raise
