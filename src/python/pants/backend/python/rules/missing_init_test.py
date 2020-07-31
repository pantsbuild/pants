# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List

import pytest

from pants.backend.python.rules import missing_init
from pants.backend.python.rules.ancestor_files import find_missing_ancestor_files
from pants.backend.python.rules.missing_init import (
    MissingInit,
    MissingInitRequest,
    MissingNonEmptyInitFiles,
)
from pants.core.util_rules import strip_source_roots
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import RootRule
from pants.testutil.engine.util import Params
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class InjectInitTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            find_missing_ancestor_files,
            *missing_init.rules(),
            *strip_source_roots.rules(),
            RootRule(MissingInitRequest),
        )

    def assert_injected(
        self,
        *,
        source_roots: List[str],
        declared_files_stripped: bool,
        original_declared_files: List[str],
        original_undeclared_empty_files: List[str],
        original_undeclared_nonempty_files: List[str],
        expected_discovered: List[str],
    ) -> None:
        for f in original_undeclared_empty_files:
            self.create_file(f, "")
        for f in original_undeclared_nonempty_files:
            self.create_file(f, "# nonempty")
        request = MissingInitRequest(
            self.make_snapshot({fp: "" for fp in original_declared_files}),
            sources_stripped=declared_files_stripped,
        )
        bootstrapper = create_options_bootstrapper(args=[f"--source-root-patterns={source_roots}"])
        result = self.request_single_product(MissingInit, Params(request, bootstrapper)).snapshot
        assert list(result.files) == sorted(expected_discovered)

    def test_unstripped(self) -> None:
        self.assert_injected(
            source_roots=["src/python", "tests/python"],
            declared_files_stripped=False,
            original_declared_files=[
                "src/python/project/lib.py",
                "src/python/project/subdir/__init__.py",
                "src/python/project/subdir/lib.py",
                "src/python/no_init/lib.py",
            ],
            original_undeclared_empty_files=[
                "src/python/project/__init__.py",
                "tests/python/project/__init__.py",
            ],
            original_undeclared_nonempty_files=[],
            expected_discovered=["src/python/project/__init__.py"],
        )

    def test_stripped(self) -> None:
        self.assert_injected(
            source_roots=["src/python", "tests/python"],
            declared_files_stripped=True,
            original_declared_files=[
                "project/lib.py",
                "project/subdir/lib.py",
                "project/subdir/__init__.py",
                "project/no_init/lib.py",
            ],
            # NB: These will strip down to end up being the same file. If they had different
            # contents, Pants would error when trying to merge them.
            original_undeclared_empty_files=[
                "src/python/project/__init__.py",
                "tests/python/project/__init__.py",
            ],
            original_undeclared_nonempty_files=[],
            expected_discovered=["project/__init__.py"],
        )

    def test_unstripped_source_root_at_buildroot(self) -> None:
        self.assert_injected(
            source_roots=["/"],
            declared_files_stripped=False,
            original_declared_files=[
                "project/lib.py",
                "project/subdir/lib.py",
                "project/subdir/__init__.py",
                "project/no_init/lib.py",
            ],
            original_undeclared_empty_files=["project/__init__.py",],
            original_undeclared_nonempty_files=[],
            expected_discovered=["project/__init__.py"],
        )

    def test_stripped_source_root_at_buildroot(self) -> None:
        self.assert_injected(
            source_roots=["/"],
            declared_files_stripped=True,
            original_declared_files=[
                "project/lib.py",
                "project/subdir/lib.py",
                "project/subdir/__init__.py",
                "project/no_init/lib.py",
            ],
            original_undeclared_empty_files=["project/__init__.py",],
            original_undeclared_nonempty_files=[],
            expected_discovered=["project/__init__.py"],
        )

    def test_nonempty_unstripped(self) -> None:
        with pytest.raises(ExecutionError) as exc:
            self.assert_injected(
                source_roots=["src/python", "tests/python"],
                declared_files_stripped=False,
                original_declared_files=[
                    "src/python/project/lib.py",
                    "src/python/project/subdir/__init__.py",
                    "src/python/project/subdir/lib.py",
                    "src/python/no_init/lib.py",
                ],
                original_undeclared_empty_files=[],
                original_undeclared_nonempty_files=[
                    "src/python/project/__init__.py",
                    "tests/python/project/__init__.py",
                ],
                expected_discovered=["src/python/project/__init__.py"],
            )
        assert len(exc.value.wrapped_exceptions) == 1
        assert isinstance(exc.value.wrapped_exceptions[0], MissingNonEmptyInitFiles)

    def test_nonempty_stripped(self) -> None:
        with pytest.raises(ExecutionError) as exc:
            self.assert_injected(
                source_roots=["src/python", "tests/python"],
                declared_files_stripped=True,
                original_declared_files=[
                    "project/lib.py",
                    "project/subdir/lib.py",
                    "project/subdir/__init__.py",
                    "project/no_init/lib.py",
                ],
                original_undeclared_empty_files=[],
                # NB: These will strip down to end up being the same file. If they had different
                # contents, Pants would error when trying to merge them.
                original_undeclared_nonempty_files=[
                    "src/python/project/__init__.py",
                    "tests/python/project/__init__.py",
                ],
                expected_discovered=["project/__init__.py"],
            )
        assert len(exc.value.wrapped_exceptions) == 1
        assert isinstance(exc.value.wrapped_exceptions[0], MissingNonEmptyInitFiles)

    def test_nonempty_unstripped_source_root_at_buildroot(self) -> None:
        with pytest.raises(ExecutionError) as exc:
            self.assert_injected(
                source_roots=["/"],
                declared_files_stripped=False,
                original_declared_files=[
                    "project/lib.py",
                    "project/subdir/lib.py",
                    "project/subdir/__init__.py",
                    "project/no_init/lib.py",
                ],
                original_undeclared_empty_files=[],
                original_undeclared_nonempty_files=["project/__init__.py",],
                expected_discovered=["project/__init__.py"],
            )
        assert len(exc.value.wrapped_exceptions) == 1
        assert isinstance(exc.value.wrapped_exceptions[0], MissingNonEmptyInitFiles)

    def test_nonempty_stripped_source_root_at_buildroot(self) -> None:
        with pytest.raises(ExecutionError) as exc:
            self.assert_injected(
                source_roots=["/"],
                declared_files_stripped=True,
                original_declared_files=[
                    "project/lib.py",
                    "project/subdir/lib.py",
                    "project/subdir/__init__.py",
                    "project/no_init/lib.py",
                ],
                original_undeclared_empty_files=[],
                original_undeclared_nonempty_files=["project/__init__.py",],
                expected_discovered=["project/__init__.py"],
            )
        assert len(exc.value.wrapped_exceptions) == 1
        assert isinstance(exc.value.wrapped_exceptions[0], MissingNonEmptyInitFiles)
