# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars, EnvironmentVarsRequest


@dataclass(frozen=True)
class EnvironmentName(EngineAwareParameter):
    """The normalized name for an environment, from `[environments-preview].names`, after applying
    things like the __local__ matcher.

    Note that we have this type, rather than only `EnvironmentTarget`, for a more efficient rule
    graph. This node impacts the equality of many downstream nodes, so we want its identity to only
    be a single string, rather than a Target instance.
    """

    val: str | None

    def debug_hint(self) -> str:
        return self.val or "<none>"


CompleteEnvironment = CompleteEnvironmentVars
EnvironmentRequest = EnvironmentVarsRequest
Environment = EnvironmentVars
