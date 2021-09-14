# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import Iterable

from pants.engine.rules import Rule, collect_rules, rule
from pants.util.memo import memoized_classproperty
from pants.util.osutil import get_normalized_arch_name, get_normalized_os_name


class Platform(Enum):
    linux_x86_64 = "linux_x86_64"
    macos_arm64 = "macos_arm64"
    macos_x86_64 = "macos_x86_64"
    linux_arm64 = "linux_arm64"

    @property
    def is_macos(self) -> bool:
        return self in [Platform.macos_arm64, Platform.macos_x86_64]

    # TODO: try to turn all of these accesses into v2 dependency injections!
    @memoized_classproperty
    def current(cls) -> Platform:
        return Platform(f"{get_normalized_os_name()}_{get_normalized_arch_name()}")


# TODO We will want to allow users to specify the execution platform for rules,
# which means replacing this singleton rule with a RootRule populated by an option.
@rule
def current_platform() -> Platform:
    return Platform.current


def rules() -> Iterable[Rule]:
    return collect_rules()
