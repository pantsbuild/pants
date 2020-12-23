# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Type, cast

from pants.base.deprecated import warn_or_error
from pants.option.option_value_container import OptionValueContainer
from pants.util.memo import memoized_property

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
    optionable_cls: Optional[Type] = None
    # A ScopeInfo may have a deprecated_scope (from its associated optionable_cls), which represents a
    # previous/deprecated name for a current/non-deprecated ScopeInfo. It may also be directly
    # deprecated via this `removal_version`, which allows for the deprecation of an entire scope,
    # including that of a SubsystemDependency (ie, deprecation of a dependency on a scoped Subsystem).
    removal_version: Optional[str] = None
    removal_hint: Optional[str] = None

    # TODO: We only memoize this to avoid repeating the deprecation warning. Revert back once the
    #  deprecation is finished.
    @memoized_property
    def description(self) -> str:
        if hasattr(self.optionable_cls, "help"):
            return cast(str, getattr(self.optionable_cls, "help"))
        warn_or_error(
            removal_version="2.3.0.dev0",
            deprecated_entity_description="not setting `help` on a `Subsystem`",
            hint=(
                "Please set the class property `help: str` for the subsystem "
                f"`{self.optionable_cls}`. In Pants 2.3, Pants will no longer look at the "
                f"docstring or help messages and it will error if `help` is not defined."
            ),
        )
        return cast(str, self._optionable_cls_attr("get_description", lambda: "")())

    @property
    def deprecated_scope(self) -> Optional[str]:
        return cast(Optional[str], self._optionable_cls_attr("deprecated_options_scope"))

    @property
    def deprecated_scope_removal_version(self) -> Optional[str]:
        return cast(
            Optional[str],
            self._optionable_cls_attr("deprecated_options_scope_removal_version"),
        )

    def _optionable_cls_attr(self, name: str, default=None):
        return getattr(self.optionable_cls, name) if self.optionable_cls else default


@dataclass(frozen=True)
class ScopedOptions:
    """A wrapper around options selected for a particular Scope."""

    scope: Scope
    options: OptionValueContainer
