# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any, Sequence

from pants.engine.fs import PathGlobs

# TODO: black and flake8 disagree about the content of this file:
#   see https://github.com/psf/black/issues/1548
# flake8: noqa: E302

# ------------------------------------------------------------------------------
# Scheduler
# ------------------------------------------------------------------------------

class PyExecutor:
    def __init__(self, core_threads: int, max_threads: int) -> None: ...

# ------------------------------------------------------------------------------
# FS
# ------------------------------------------------------------------------------

def default_cache_path() -> str: ...

# TODO: Really, `paths` should be `Sequence[str]`. Fix and update call sites so that we don't
#  cast to `tuple()` when not necessary.
def match_path_globs(path_globs: PathGlobs, paths: tuple[str, ...]) -> str: ...

class PyDigest:
    def __init__(self, fingerprint: str, serialized_bytes_length: int) -> None: ...
    @property
    def fingerprint(self) -> str: ...
    @property
    def serialized_bytes_length(self) -> int: ...
    def __eq__(self, other: PyDigest | Any) -> bool: ...
    def __hash__(self) -> int: ...

class PySnapshot:
    def __init__(self) -> None: ...
    @classmethod
    def _create_for_testing(
        cls, digest: PyDigest, files: Sequence[str], dirs: Sequence[str]
    ) -> PySnapshot: ...
    @property
    def digest(self) -> PyDigest: ...
    @property
    def dirs(self) -> tuple[str, ...]: ...
    @property
    def files(self) -> tuple[str, ...]: ...
    def __eq__(self, other: PySnapshot | Any) -> bool: ...
    def __hash__(self) -> int: ...

# ------------------------------------------------------------------------------
# Workunits
# ------------------------------------------------------------------------------

def all_counter_names() -> list[str]: ...

# ------------------------------------------------------------------------------
# Nailgun
# ------------------------------------------------------------------------------

class PyNailgunClient:
    def __init__(self, port: int, executor: PyExecutor) -> None: ...
    def execute(self, command: str, args: list[str], env: dict[str, str]) -> int: ...

class PantsdConnectionException(Exception):
    pass

class PantsdClientException(Exception):
    pass

# ------------------------------------------------------------------------------
# Testutil
# ------------------------------------------------------------------------------

class PyStubCASBuilder:
    def always_errors(self) -> PyStubCASBuilder: ...
    def build(self, executor: PyExecutor) -> PyStubCAS: ...

class PyStubCAS:
    @classmethod
    def builder(cls) -> PyStubCASBuilder: ...
    @property
    def address(self) -> str: ...
