# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import Iterable

from pants.base import deprecated
from pants.engine.rules import Rule, collect_rules, rule
from pants.util.memo import memoized_classproperty
from pants.util.osutil import get_normalized_arch_name, get_normalized_os_name


class Platform(Enum):
    linux_x86_64 = "linux_x86_64"
    macos_arm64 = "macos_arm64"
    macos_x86_64 = "macos_x86_64"

    @classmethod
    def _missing_(cls, old_platform):
        """Support access to old Intel platform designators by name."""
        if old_platform == "linux":
            Platform.deprecated_due_to_no_architecture()
            return cls.linux_x86_64
        elif old_platform == "darwin":
            Platform.deprecated_due_to_no_architecture()
            return cls.macos_x86_64
        else:
            return None

    @memoized_classproperty
    def linux(cls) -> Platform:
        """Deprecated, backward-compatible notation for linux on Intel."""
        Platform.deprecated_due_to_no_architecture()
        return Platform.linux_x86_64

    @memoized_classproperty
    def darwin(cls) -> Platform:
        """Deprecated, backward-compatible notation for Mac OS on Intel."""
        Platform.deprecated_due_to_no_architecture()
        return Platform.macos_x86_64

    @property
    def is_macos(self) -> bool:
        return self in [Platform.macos_arm64, Platform.macos_x86_64]

    def matches(self, value):
        """Returns true if the provided value is the value for this platform, or if the provided
        value is the value for the deprecated platform symbol from before we qualified based on
        architecture.

        When deprecation is complete, replace uses of this method with `platform.value == value`.
        """
        if self.value == value:
            return True
        elif value == "linux" and self == Platform.linux_x86_64:
            Platform.deprecated_due_to_no_architecture()
            return True
        elif value == "darwin" and self == Platform.macos_x86_64:
            Platform.deprecated_due_to_no_architecture()
            return True
        else:
            return False

    # TODO: try to turn all of these accesses into v2 dependency injections!
    @memoized_classproperty
    def current(cls) -> Platform:
        return Platform(f"{get_normalized_os_name()}_{get_normalized_arch_name()}")

    @staticmethod
    def deprecated_due_to_no_architecture():
        deprecated.warn_or_error(
            removal_version="2.8.0.dev0",
            entity="Using a platform without an architecture qualifier (`linux` or `darwin`). `x86_64` is assumed for now.",
            hint="Use the qualified platforms `linux_x86_64` or `macos_x86_64` for Intel architectures, or `macos_arm64` for ARM.",
            print_warning=True,
        )


# TODO We will want to allow users to specify the execution platform for rules,
# which means replacing this singleton rule with a RootRule populated by an option.
@rule
def current_platform() -> Platform:
    return Platform.current


def rules() -> Iterable[Rule]:
    return collect_rules()
