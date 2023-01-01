# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.base.deprecated import warn_or_error
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars, EnvironmentVarsRequest

LOCAL_ENVIRONMENT_MATCHER = "__local__"


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


def __getattr__(name):
    if name == "EnvironmentName":
        return EnvironmentName
    if name == "CompleteEnvironment":
        warn_or_error(
            "2.17.0.dev0",
            "`pants.engine.environment.CompleteEnvironment`",
            "Use `pants.engine.env_vars.CompleteEnvironmentVars`.",
        )
        return CompleteEnvironmentVars
    if name == "EnvironmentRequest":
        warn_or_error(
            "2.17.0.dev0",
            "`pants.engine.environment.EnvironmentRequest`",
            "Use `pants.engine.env_vars.EnvironmentVarsRequest`.",
        )
        return EnvironmentVarsRequest
    if name == "Environment":
        warn_or_error(
            "2.17.0.dev0",
            "`pants.engine.environment.Environment`",
            "Use `pants.engine.env_vars.EnvironmentVars`.",
        )
        return EnvironmentVars
    raise AttributeError(name)
