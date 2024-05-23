# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.engine.engine_aware import EngineAwareParameter

# Reserved sentinel value directing Pants to find applicable local environment.
LOCAL_ENVIRONMENT_MATCHER = "__local__"

# Reserved sentinel value representing execution within the workspace and not local sandbox.
# Note: This is temporary until support for `workspace_environment` target type lands.
__LOCAL_WORKSPACE_ENV_NAME = "__local_workspace__"


@dataclass(frozen=True)
class EnvironmentName(EngineAwareParameter):
    """The normalized name for an environment, from `[environments-preview].names`, after applying
    things like the __local__ matcher.

    Note that we have this type, rather than only `EnvironmentTarget`, for a more efficient rule
    graph. This node impacts the equality of many downstream nodes, so we want its identity to only
    be a single string, rather than a Target instance.
    """

    val: str | None

    def debug_hint(self) -> str | None:
        return f"environment:{self.val}" if self.val else None


@dataclass(frozen=True)
class ChosenLocalEnvironmentName:
    """Which environment name from `[environments-preview].names` that __local__ resolves to."""

    val: EnvironmentName
