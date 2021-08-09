# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Type, cast

from pants.option.option_value_container import OptionValueContainer

GLOBAL_SCOPE = ""
GLOBAL_SCOPE_CONFIG_SECTION = "GLOBAL"


def normalize_scope(scope: str):
    return scope.lower().replace("-", "_")


@dataclass(frozen=True)
class Scope:
    """An options scope."""

    scope: str


@dataclass(frozen=True, order=True)
class ScopeInfo:
    """Information about a scope."""

    scope: str
    subsystem_cls: Optional[Type] = None
    # A ScopeInfo may have a deprecated_scope (from its associated subsystem_cls), which represents
    # a previous/deprecated name for a current/non-deprecated ScopeInfo. It may also be directly
    # deprecated via this `removal_version`, which allows for the deprecation of an entire scope.
    removal_version: Optional[str] = None
    removal_hint: Optional[str] = None

    # command line goal scope flag
    is_goal: bool = False

    @property
    def description(self) -> str:
        return cast(str, getattr(self.subsystem_cls, "help"))

    @property
    def deprecated_scope(self) -> Optional[str]:
        return cast(Optional[str], self._subsystem_cls_attr("deprecated_options_scope"))

    @property
    def deprecated_scope_removal_version(self) -> Optional[str]:
        return cast(
            Optional[str],
            self._subsystem_cls_attr("deprecated_options_scope_removal_version"),
        )

    def _subsystem_cls_attr(self, name: str, default=None):
        return getattr(self.subsystem_cls, name) if self.subsystem_cls else default


@dataclass(frozen=True)
class ScopedOptions:
    """A wrapper around options selected for a particular Scope."""

    scope: Scope
    options: OptionValueContainer
