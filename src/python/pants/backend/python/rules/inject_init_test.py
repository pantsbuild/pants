# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional

from pants.backend.python.rules.inject_init import (
    InitInjectedSnapshot,
    InjectInitRequest,
    inject_missing_init_files,
)
from pants.engine.fs import Digest, FilesContent
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class InjectInitTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            inject_missing_init_files,
            RootRule(InjectInitRequest),
            RootRule(Digest),
        )

    def assert_injected(
        self,
        *,
        original_files: List[str],
        expected_added: List[str],
        expected_discovered: Optional[List[str]] = None,
        sources_stripped=True,
    ) -> None:
        expected_discovered = expected_discovered or ()
        request = InjectInitRequest(
            self.make_snapshot({fp: "# python code" for fp in original_files}),
            sources_stripped=sources_stripped,
        )
        result = self.request_single_product(
            InitInjectedSnapshot,
            Params(
                request, create_options_bootstrapper(args=["--source-root-patterns=['src/python']"])
            ),
        ).snapshot
        assert list(result.files) == sorted(
            [*original_files, *expected_added, *expected_discovered]
        )
        # Ensure all original `__init__.py` are preserved with their original content.
        materialized_original_inits = [
            fc
            for fc in self.request_single_product(FilesContent, result.digest)
            if fc.path.endswith("__init__.py")
            and (fc.path in original_files or fc.path in expected_discovered)
        ]
        for original_init in materialized_original_inits:
            assert (
                original_init.content == b"# python code"
            ), f"{original_init} does not have its original content preserved."

    def test_no_inits_present(self) -> None:
        self.assert_injected(
            original_files=["lib.py", "subdir/lib.py"], expected_added=["subdir/__init__.py"],
        )
        self.assert_injected(
            original_files=["a/b/lib.py", "a/b/subdir/lib.py"],
            expected_added=["a/__init__.py", "a/b/__init__.py", "a/b/subdir/__init__.py",],
        )

    def test_preserves_original_inits(self) -> None:
        self.assert_injected(
            original_files=["lib.py", "__init__.py", "subdir/lib.py"],
            expected_added=["subdir/__init__.py"],
        )
        self.assert_injected(
            original_files=[
                "a/b/lib.py",
                "a/b/__init__.py",
                "a/b/subdir/lib.py",
                "a/b/subdir/__init__.py",
            ],
            expected_added=["a/__init__.py"],
        )
        # No missing `__init__.py` files
        self.assert_injected(
            original_files=["lib.py", "__init__.py", "subdir/lib.py", "subdir/__init__.py"],
            expected_added=[],
        )

    def test_finds_undeclared_original_inits(self) -> None:
        self.create_file("a/__init__.py", "# python code")
        self.create_file("a/b/__init__.py", "# python code")
        self.assert_injected(
            original_files=["a/b/subdir/lib.py"],
            expected_added=["a/b/subdir/__init__.py"],
            expected_discovered=["a/__init__.py", "a/b/__init__.py"],
        )

    def test_source_roots_unstripped(self) -> None:
        self.assert_injected(
            original_files=[
                "src/python/lib.py",
                "src/python/subdir/lib.py",
                "src/python/subdir/__init__.py",
                "src/python/another_subdir/lib.py",
            ],
            expected_added=["src/python/another_subdir/__init__.py"],
            sources_stripped=False,
        )
