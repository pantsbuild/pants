# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum

from pants.base.deprecated import deprecated
from pants.util.memo import memoized_classproperty
from pants.util.osutil import get_normalized_arch_name, get_normalized_os_name


class Platform(Enum):
    linux_arm64 = "linux_arm64"
    linux_x86_64 = "linux_x86_64"
    macos_arm64 = "macos_arm64"
    macos_x86_64 = "macos_x86_64"

    @property
    def is_macos(self) -> bool:
        return self in [Platform.macos_arm64, Platform.macos_x86_64]

    @memoized_classproperty
    @deprecated(
        "2.16.0.dev1",
        (
            "The `Platform` to use is dependent on a `@rule`'s position in the `@rule` graph. "
            "Request the `Platform` to use as a `@rule` argument to get the appropriate `Platform`."
        ),
    )
    def current(cls) -> Platform:
        return cls.create_for_localhost()

    @classmethod
    def create_for_localhost(cls) -> Platform:
        """Creates a Platform instance for localhost.

        This method should never be accessed directly by `@rules`: instead, to get the currently
        active `Platform`, they should request a `Platform` as a positional argument.
        """
        return Platform(f"{get_normalized_os_name()}_{get_normalized_arch_name()}")
