# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Optional, Type, cast

from pants.option.option_value_container import OptionValueContainer

if TYPE_CHECKING:
    from pants.option.optionable import Optionable  # noqa: F401

GLOBAL_SCOPE = ""
GLOBAL_SCOPE_CONFIG_SECTION = "GLOBAL"


@dataclass(frozen=True)
class Scope:
    """An options scope."""

    scope: str


@dataclass(frozen=True, order=True)
class ScopeInfo:
    """Information about a scope."""

    scope: str
    category: str
    optionable_cls: Optional[Type["Optionable"]] = None
    # A ScopeInfo may have a deprecated_scope (from its associated optionable_cls), which represents a
    # previous/deprecated name for a current/non-deprecated ScopeInfo. It may also be directly
    # deprecated via this `removal_version`, which allows for the deprecation of an entire scope,
    # including that of a SubsystemDependency (ie, deprecation of a dependency on a scoped Subsystem).
    removal_version: Optional[str] = None
    removal_hint: Optional[str] = None

    # Symbolic constants for different categories of scope.
    GLOBAL: ClassVar[str] = "GLOBAL"
    GOAL: ClassVar[str] = "GOAL"
    GOAL_V1: ClassVar[str] = "GOAL_V1"
    TASK: ClassVar[str] = "TASK"
    SUBSYSTEM: ClassVar[str] = "SUBSYSTEM"
    INTERMEDIATE: ClassVar[
        str
    ] = "INTERMEDIATE"  # Scope added automatically to fill out the scope hierarchy.

    @property
    def description(self) -> str:
        return cast(str, self._optionable_cls_attr("get_description", lambda: "")())

    @property
    def deprecated_scope(self) -> Optional[str]:
        return cast(Optional[str], self._optionable_cls_attr("deprecated_options_scope"))

    @property
    def deprecated_scope_removal_version(self) -> Optional[str]:
        return cast(
            Optional[str], self._optionable_cls_attr("deprecated_options_scope_removal_version"),
        )

    def _optionable_cls_attr(self, name: str, default=None):
        return getattr(self.optionable_cls, name) if self.optionable_cls else default


@dataclass(frozen=True)
class ScopedOptions:
    """A wrapper around options selected for a particular Scope."""

    scope: Scope
    options: OptionValueContainer
