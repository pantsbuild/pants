# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from pants.util.meta import SingletonMetaclass


class BuildRoot(metaclass=SingletonMetaclass):
    """Represents the global workspace build root.

    By default a Pants workspace is defined by a root directory where one of multiple sentinel files
    reside, such as `pants` or `BUILD_ROOT`. This path can also be manipulated through this
    interface for re-location of the build root in tests.
    """

    sentinel_files = ["pants", "BUILDROOT", "BUILD_ROOT"]

    class NotFoundError(Exception):
        """Raised when unable to find the current workspace build root."""

    def find_buildroot(self) -> str:
        buildroot = Path.cwd().resolve()
        while not any((buildroot / sentinel).is_file() for sentinel in self.sentinel_files):
            if buildroot != buildroot.parent:
                buildroot = buildroot.parent
            else:
                raise self.NotFoundError(
                    "No build root detected. Pants detects the build root by looking for at least one file "
                    f"from {self.sentinel_files} in the cwd and its ancestors. If you have none of these "
                    f"files, you can create an empty file in your build root."
                )
        return str(buildroot)

    def __init__(self) -> None:
        self._root_dir: Optional[str] = None

    @property
    def pathlib_path(self) -> Path:
        return Path(self.path)

    @property
    def path(self) -> str:
        """Returns the build root for the current workspace."""
        if self._root_dir is None:
            # This env variable is for testing purpose.
            override_buildroot = os.environ.get("PANTS_BUILDROOT_OVERRIDE", None)
            if override_buildroot:
                self._root_dir = override_buildroot
            else:
                self._root_dir = os.path.realpath(self.find_buildroot())
        return self._root_dir

    @path.setter
    def path(self, root_dir: str) -> None:
        """Manually establishes the build root for the current workspace."""
        path = os.path.realpath(root_dir)
        if not os.path.exists(path):
            raise ValueError(f"Build root does not exist: {root_dir}")
        self._root_dir = path

    def reset(self) -> None:
        """Clears the last calculated build root for the current workspace."""
        self._root_dir = None

    def __str__(self) -> str:
        return f"BuildRoot({self._root_dir})"

    @contextmanager
    def temporary(self, path: str) -> Iterator[None]:
        """Establishes a temporary build root, restoring the prior build root on exit."""
        if path is None:
            raise ValueError("Can only temporarily establish a build root given a path.")
        prior = self._root_dir
        self._root_dir = path
        try:
            yield
        finally:
            self._root_dir = prior
