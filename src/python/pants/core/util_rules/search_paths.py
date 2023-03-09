# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.core.util_rules.environments import EnvironmentTarget, LocalEnvironmentTarget
from pants.engine.rules import Rule, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class ValidateSearchPathsRequest:
    env_tgt: EnvironmentTarget
    search_paths: tuple[str, ...]
    option_origin: str
    environment_key: str
    is_default: bool
    local_only: FrozenOrderedSet[str]


class ValidatedSearchPaths(FrozenOrderedSet):
    """Search paths that are valid for the current target environment."""


@rule(level=LogLevel.DEBUG)
async def validate_search_paths(request: ValidateSearchPathsRequest) -> ValidatedSearchPaths:
    """Checks for special search path strings, and errors if any are invalid for the environment.

    This will return:
    * The search paths, unaltered, for local/undefined environments, OR
    * The search paths, with invalid tokens removed, if the provided value was unaltered from the
      default value in the options system.
    * The search paths unaltered, if the search paths are all valid tokens for this environment

    If the environment is non-local and there are invalid tokens for those environments, raise
    `ValueError`.
    """

    env = request.env_tgt.val
    search_paths = request.search_paths

    if env is None or isinstance(env, LocalEnvironmentTarget):
        return ValidatedSearchPaths(search_paths)

    if request.is_default:
        # Strip out the not-allowed special strings from search_paths.
        # An error will occur on the off chance the non-local environment expects local_only tokens,
        # but there's nothing we can do here to detect it.
        return ValidatedSearchPaths(path for path in search_paths if path not in request.local_only)

    any_not_allowed = set(search_paths) & request.local_only
    if any_not_allowed:
        env_type = type(env)
        raise ValueError(
            softwrap(
                f"`{request.option_origin}` is configured to use local discovery "
                f"tools, which do not work in {env_type.__name__} runtime environments. To fix "
                f"this, set the value of `{request.environment_key}` in the `{env.alias}` "
                f"defined at `{env.address}` to contain only hardcoded paths or the `<PATH>` "
                "special string."
            )
        )

    return ValidatedSearchPaths(search_paths)


def rules() -> Iterable[Rule]:
    return collect_rules()
