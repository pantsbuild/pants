# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum

from pants.util.osutil import get_normalized_arch_name, get_normalized_os_name


class PlatformError(Exception):
    """Raise when an attempt is made to execute a process on a platform where it cannot succeed.

    E.g., because it requires a tool that is not supported on the platform.
    """


class Platform(Enum):
    linux_arm64 = "linux_arm64"
    linux_x86_64 = "linux_x86_64"
    macos_arm64 = "macos_arm64"
    macos_x86_64 = "macos_x86_64"

    @property
    def is_macos(self) -> bool:
        return self in [Platform.macos_arm64, Platform.macos_x86_64]

    @classmethod
    def create_for_localhost(cls) -> Platform:
        """Creates a Platform instance for localhost.

        This method should never be accessed directly by `@rules`: instead, to get the currently
        active `Platform`, they should request a `Platform` as a positional argument.
        """
        return Platform(f"{get_normalized_os_name()}_{get_normalized_arch_name()}")

    def for_linux(self) -> Platform:
        """Returns a Platform instance representing Linux on the Platform's architecture.

        Useful for fetching docker images runnable directly on the local architecture.
        """
        if self == Platform.macos_x86_64:
            return Platform.linux_x86_64
        elif self == Platform.macos_arm64:
            return Platform.linux_arm64
        else:
            return self
