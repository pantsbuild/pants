# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from textwrap import dedent  # noqa: PNT20

from pants.engine.internals.native_engine import Digest
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class PythonBuildStandaloneBinary:
    """A Python interpreter for use by `@rule` code as an alternative to BashBinary scripts.

    @TODO:...
    """

    SYMLINK_DIRNAME = ".python-build-standalone"

    _path: str
    """The path to the Python binary inside the immutable input symlink."""
    _digest: Digest

    @property
    def path(self) -> str:
        return f"{PythonBuildStandaloneBinary.SYMLINK_DIRNAME}/{self._path}"

    @property
    def immutable_input_digests(self) -> FrozenDict[str, Digest]:
        return FrozenDict({PythonBuildStandaloneBinary.SYMLINK_DIRNAME: self._digest})


@dataclass(frozen=True)
class GunzipBinaryRequest:
    pass


@dataclass(frozen=True)
class GunzipBinary:
    python_binary: PythonBuildStandaloneBinary

    def extract_archive_argv(self, archive_path: str, extract_path: str) -> tuple[str, ...]:
        archive_name = os.path.basename(archive_path)
        dest_file_name = os.path.splitext(archive_name)[0]
        dest_path = os.path.join(extract_path, dest_file_name)
        script = dedent(
            f"""
            import gzip
            import shutil
            with gzip.GzipFile(filename={archive_path!r}, mode="rb") as source:
                with open({dest_path!r}, "wb") as dest:
                    shutil.copyfileobj(source, dest)
            """
        )
        return (self.python_binary.path, "-c", script)
