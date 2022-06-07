# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class Return:
    """Indicates that a Node successfully returned a value."""

    value: Any


_Frame = Tuple[str, Optional[str]]


@dataclass(frozen=True)
class Throw:
    """Indicates that a Node should have been able to return a value, but failed."""

    exc: Exception
    python_traceback: str | None = None
    engine_traceback: tuple[_Frame, ...] = ()

    def _render_frame(self, frame: _Frame, include_trace_on_error: bool) -> str | None:
        """Renders either only the description (if set), or both the name and description."""
        name, desc = frame

        if include_trace_on_error:
            return f"{name}\n    {desc or '..'}"
        elif desc:
            return f"{desc}"
        else:
            return None

    def render(self, include_trace_on_error: bool) -> str:
        all_rendered_frames = [
            self._render_frame(frame, include_trace_on_error)
            for frame in reversed(self.engine_traceback)
        ]
        rendered_frames = [f for f in all_rendered_frames if f]
        engine_traceback_str = ""
        if rendered_frames:
            sep = "\n  in "
            engine_traceback_str = "Engine traceback:" + sep + sep.join(rendered_frames) + "\n\n"
        if include_trace_on_error:
            python_traceback_str = f"{self.python_traceback}" if self.python_traceback else ""
        else:
            python_traceback_str = f"{type(self.exc).__name__}: {str(self.exc)}"
        return f"{engine_traceback_str}{python_traceback_str}"
