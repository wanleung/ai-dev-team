"""FallbackLLMBackend — tries backends in order, switches on connection errors."""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING

from agents.backends.base import LLMBackend, FALLBACK_ERRORS, QuotaExhaustedError

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class FallbackLLMBackend(LLMBackend):
    """Ordered list of LLMBackend instances — tries each on connection failure.

    On a FALLBACK_ERRORS exception from backend N:
      - Prints a visible ⚠️ warning to stdout
      - Passes the full messages list (with history) to backend N+1
      - If all backends fail, re-raises the last exception

    On a QuotaExhaustedError, the backend is also permanently marked dead
    for the lifetime of this object — subsequent calls skip it entirely.

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
        self._dead: set[int] = set()  # id(backend) for permanently exhausted backends

    def _active_backends(self) -> list[LLMBackend]:
        """Return backends that have not been permanently marked dead."""
        return [b for b in self._backends if id(b) not in self._dead]

    def _log_fallback(self, backend: LLMBackend, exc: BaseException, active: list, idx: int) -> None:
        if idx < len(active) - 1:
            logger.warning(
                "⚠️  %s unreachable (%s: %s), falling back to %s",
                backend.model, type(exc).__name__, str(exc)[:120], active[idx + 1].model,
            )

    @property
    def model(self) -> str:
        return self._backends[0].model

    def supports_tools(self) -> bool:
        return self._backends[0].supports_tools()

    def call(self, messages: list[dict], run_id: str | None = None,
             on_token: "Callable[[str], None] | None" = None) -> str:
        active = self._active_backends()
        if not active:
            raise RuntimeError("All backends permanently exhausted (quota exceeded on all)")
        for i, backend in enumerate(active):
            try:
                return backend.call(messages, on_token=on_token)
            except QuotaExhaustedError as exc:
                self._dead.add(id(backend))
                self._log_fallback(backend, exc, active, i)
                if i >= len(active) - 1:
                    raise
            except FALLBACK_ERRORS as exc:
                self._log_fallback(backend, exc, active, i)
                if i >= len(active) - 1:
                    raise

    def call_with_tools(
        self,
        messages: list[dict],
        tools: "ToolRegistry",
        max_turns: int = 8,
        run_id: str | None = None,
    ) -> str:
        tool_backends = [b for b in self._active_backends() if b.supports_tools()]
        if not tool_backends:
            raise RuntimeError(
                f"No tool-capable backend available in FallbackLLMBackend "
                f"(backends: {[b.model for b in self._backends]})"
            )
        for i, backend in enumerate(tool_backends):
            try:
                return backend.call_with_tools(messages, tools, max_turns)
            except QuotaExhaustedError as exc:
                self._dead.add(id(backend))
                self._log_fallback(backend, exc, tool_backends, i)
                if i >= len(tool_backends) - 1:
                    raise
            except FALLBACK_ERRORS as exc:
                self._log_fallback(backend, exc, tool_backends, i)
                if i >= len(tool_backends) - 1:
                    raise
