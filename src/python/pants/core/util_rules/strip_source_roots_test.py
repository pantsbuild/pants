# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from typing import List, Optional

import pytest

from pants.core.util_rules import determine_source_files
from pants.core.util_rules.determine_source_files import SourceFiles
from pants.core.util_rules.strip_source_roots import StrippedSourceFiles
from pants.core.util_rules.strip_source_roots import rules as strip_source_root_rules
from pants.engine.fs import EMPTY_SNAPSHOT
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import RootRule
from pants.testutil.engine.util import Params
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class StripSourceRootsTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *strip_source_root_rules(),
            *determine_source_files.rules(),
            RootRule(SourceFiles),
        )

    def get_stripped_files(
        self, request: SourceFiles, *, args: Optional[List[str]] = None,
    ) -> List[str]:
        args = args or []
        has_source_root_patterns = False
        for arg in args:
            if arg.startswith("--source-root-patterns"):
                has_source_root_patterns = True
                break
        if not has_source_root_patterns:
            source_root_patterns = ["src/python", "src/java", "tests/python"]
            args.append(f"--source-root-patterns={json.dumps(source_root_patterns)}")
        result = self.request_single_product(
            StrippedSourceFiles, Params(request, create_options_bootstrapper(args=args)),
        )
        return list(result.snapshot.files)

    def test_strip_snapshot(self) -> None:
        def get_stripped_files_for_snapshot(
            paths: List[str], *, args: Optional[List[str]] = None,
        ) -> List[str]:
            input_snapshot = self.make_snapshot_of_empty_files(paths)
            request = SourceFiles(input_snapshot, ())
            return self.get_stripped_files(request, args=args)

        # Normal source roots
        assert get_stripped_files_for_snapshot(["src/python/project/example.py"]) == [
            "project/example.py"
        ]
        assert get_stripped_files_for_snapshot(["src/python/project/example.py"],) == [
            "project/example.py"
        ]

        assert get_stripped_files_for_snapshot(["src/java/com/project/example.java"]) == [
            "com/project/example.java"
        ]
        assert get_stripped_files_for_snapshot(["tests/python/project_test/example.py"]) == [
            "project_test/example.py"
        ]

        # Unrecognized source root
        unrecognized_source_root = "no-source-root/example.txt"
        with pytest.raises(ExecutionError) as exc:
            get_stripped_files_for_snapshot([unrecognized_source_root])
        assert f"NoSourceRootError: No source root found for `{unrecognized_source_root}`." in str(
            exc.value
        )

        # Support for multiple source roots
        file_names = ["src/python/project/example.py", "src/java/com/project/example.java"]
        assert get_stripped_files_for_snapshot(file_names) == [
            "com/project/example.java",
            "project/example.py",
        ]

        # Test a source root at the repo root. We have performance optimizations for this case
        # because there is nothing to strip.
        source_root_config = [f"--source-root-patterns={json.dumps(['/'])}"]

        assert get_stripped_files_for_snapshot(
            ["project/f1.py", "project/f2.py"], args=source_root_config,
        ) == ["project/f1.py", "project/f2.py"]

        assert get_stripped_files_for_snapshot(
            ["dir1/f.py", "dir2/f.py"], args=source_root_config,
        ) == ["dir1/f.py", "dir2/f.py"]

        # Gracefully handle an empty snapshot
        assert self.get_stripped_files(SourceFiles(EMPTY_SNAPSHOT, ())) == []
