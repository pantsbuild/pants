# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List

from pants.backend.python.rules.inject_ancestor_files import (
    AncestorFiles,
    AncestorFilesRequest,
    find_missing_ancestor_files,
    identify_missing_ancestor_files,
)
from pants.core.util_rules import strip_source_roots
from pants.engine.fs import DigestContents
from pants.engine.rules import RootRule
from pants.testutil.engine.util import Params
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class InjectAncestorFilesTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            find_missing_ancestor_files,
            *strip_source_roots.rules(),
            RootRule(AncestorFilesRequest),
        )

    def assert_injected(
        self,
        *,
        declared_files_stripped: bool,
        original_declared_files: List[str],
        original_undeclared_files: List[str],
        expected_discovered: List[str],
    ) -> None:
        for f in original_undeclared_files:
            self.create_file(f, "# undeclared")
        request = AncestorFilesRequest(
            "__init__.py",
            self.make_snapshot({fp: "# declared" for fp in original_declared_files}),
            sources_stripped=declared_files_stripped,
        )
        bootstrapper = create_options_bootstrapper(
            args=["--source-root-patterns=['src/python', 'tests/python']"]
        )
        result = self.request_single_product(AncestorFiles, Params(request, bootstrapper)).snapshot
        assert list(result.files) == sorted(expected_discovered)

        materialized_result = self.request_single_product(DigestContents, result.digest)
        for file_content in materialized_result:
            path = file_content.path
            if not path.endswith("__init__.py"):
                continue
            assert path in original_declared_files or path in expected_discovered
            expected = b"# declared" if path in original_declared_files else b"# undeclared"
            assert file_content.content == expected

    def test_unstripped(self) -> None:
        self.assert_injected(
            declared_files_stripped=False,
            original_declared_files=[
                "src/python/project/lib.py",
                "src/python/project/subdir/__init__.py",
                "src/python/project/subdir/lib.py",
                "src/python/no_init/lib.py",
            ],
            original_undeclared_files=[
                "src/python/project/__init__.py",
                "tests/python/project/__init__.py",
            ],
            expected_discovered=["src/python/project/__init__.py"],
        )

    def test_stripped(self) -> None:
        self.assert_injected(
            declared_files_stripped=True,
            original_declared_files=[
                "project/lib.py",
                "project/subdir/lib.py",
                "project/subdir/__init__.py",
                "project/no_init/lib.py",
            ],
            # NB: These will strip down to end up being the same file. If they had different
            # contents, Pants would error when trying to merge them.
            original_undeclared_files=[
                "src/python/project/__init__.py",
                "tests/python/project/__init__.py",
            ],
            expected_discovered=["project/__init__.py"],
        )


def test_identify_missing_ancestor_files() -> None:
    assert {"a/__init__.py", "a/b/__init__.py", "a/b/c/d/__init__.py"} == set(
        identify_missing_ancestor_files(
            "__init__.py", ["a/b/foo.py", "a/b/c/__init__.py", "a/b/c/d/bar.py", "a/e/__init__.py"]
        )
    )

    assert {
        "src/__init__.py",
        "src/python/__init__.py",
        "src/python/a/__init__.py",
        "src/python/a/b/__init__.py",
        "src/python/a/b/c/d/__init__.py",
    } == set(
        identify_missing_ancestor_files(
            "__init__.py",
            [
                "src/python/a/b/foo.py",
                "src/python/a/b/c/__init__.py",
                "src/python/a/b/c/d/bar.py",
                "src/python/a/e/__init__.py",
            ],
        )
    )
