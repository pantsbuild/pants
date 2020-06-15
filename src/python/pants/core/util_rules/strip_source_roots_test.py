# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from typing import Dict, List, Optional, Tuple, Type, Union

import pytest

from pants.core.target_types import FilesSources
from pants.core.util_rules.strip_source_roots import (
    SourceRootStrippedSources,
    StripSnapshotRequest,
    StripSourcesFieldRequest,
)
from pants.core.util_rules.strip_source_roots import rules as strip_source_root_rules
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_SNAPSHOT
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.selectors import Params
from pants.engine.target import Sources as SourcesField
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase

StrippedResponseData = Tuple[List[str], Dict[str, Tuple[str, ...]]]


class StripSourceRootsTest(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), *strip_source_root_rules())

    def get_stripped_files(
        self,
        request: Union[StripSnapshotRequest, StripSourcesFieldRequest],
        *,
        args: Optional[List[str]] = None,
    ) -> StrippedResponseData:
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
            SourceRootStrippedSources, Params(request, create_options_bootstrapper(args=args)),
        )
        return list(result.snapshot.files), dict(result.root_to_relfiles)

    def test_strip_snapshot(self) -> None:
        def get_stripped_files_for_snapshot(
            paths: List[str],
            *,
            use_representative_path: bool = True,
            args: Optional[List[str]] = None,
        ) -> StrippedResponseData:
            input_snapshot = self.make_snapshot_of_empty_files(paths)
            request = StripSnapshotRequest(
                input_snapshot, representative_path=paths[0] if use_representative_path else None
            )
            return self.get_stripped_files(request, args=args)

        # Normal source roots
        assert get_stripped_files_for_snapshot(["src/python/project/example.py"]) == (
            ["project/example.py"],
            {"src/python": ("project/example.py",)},
        )
        assert get_stripped_files_for_snapshot(
            ["src/python/project/example.py"], use_representative_path=False
        ) == (["project/example.py"], {"src/python": ("project/example.py",)})
        assert get_stripped_files_for_snapshot(["src/java/com/project/example.java"]) == (
            ["com/project/example.java"],
            {"src/java": ("com/project/example.java",)},
        )
        assert get_stripped_files_for_snapshot(["tests/python/project_test/example.py"]) == (
            ["project_test/example.py"],
            {"tests/python": ("project_test/example.py",)},
        )

        # Unrecognized source root
        unrecognized_source_root = "no-source-root/example.txt"
        with pytest.raises(ExecutionError) as exc:
            get_stripped_files_for_snapshot([unrecognized_source_root])
        assert "NoSourceRootError: No source root found for `no-source-root`." in str(exc.value)

        # Support for multiple source roots
        file_names = ["src/python/project/example.py", "src/java/com/project/example.java"]
        with pytest.raises(ExecutionError) as exc:
            get_stripped_files_for_snapshot(file_names, use_representative_path=True)
        assert "Cannot strip prefix src/python" in str(exc.value)
        assert get_stripped_files_for_snapshot(file_names, use_representative_path=False) == (
            ["com/project/example.java", "project/example.py"],
            {"src/python": ("project/example.py",), "src/java": ("com/project/example.java",)},
        )

        # Test a source root at the repo root. We have performance optimizations for this case
        # because there is nothing to strip.
        source_root_config = [f"--source-root-patterns={json.dumps(['/'])}"]
        assert get_stripped_files_for_snapshot(
            ["project/f1.py", "project/f2.py"],
            args=source_root_config,
            use_representative_path=True,
        ) == (["project/f1.py", "project/f2.py"], {".": ("project/f1.py", "project/f2.py")})
        assert get_stripped_files_for_snapshot(
            ["dir1/f.py", "dir2/f.py"], args=source_root_config, use_representative_path=False
        ) == (["dir1/f.py", "dir2/f.py"], {".": ("dir1/f.py", "dir2/f.py")})

        # Gracefully handle an empty snapshot
        assert self.get_stripped_files(StripSnapshotRequest(EMPTY_SNAPSHOT)) == ([], {})

    def test_strip_sources_field(self) -> None:
        source_root = "src/python/project"

        def get_stripped_files_for_sources_field(
            *,
            source_files: Optional[List[str]],
            sources_field_cls: Type[SourcesField] = SourcesField,
            specified_source_files: Optional[List[str]] = None,
        ) -> StrippedResponseData:
            if source_files:
                self.create_files(path=source_root, files=source_files)
            sources_field = sources_field_cls(
                source_files, address=Address.parse(f"{source_root}:lib")
            )
            specified_sources_snapshot = (
                None
                if not specified_source_files
                else self.make_snapshot_of_empty_files(
                    f"{source_root}/{f}" for f in specified_source_files
                )
            )
            return self.get_stripped_files(
                StripSourcesFieldRequest(
                    sources_field, specified_files_snapshot=specified_sources_snapshot,
                )
            )

        # normal sources
        assert get_stripped_files_for_sources_field(source_files=["f1.py", "f2.py"]) == (
            ["project/f1.py", "project/f2.py"],
            {"src/python": ("project/f1.py", "project/f2.py")},
        )

        # empty sources
        assert get_stripped_files_for_sources_field(source_files=None) == ([], {})

        # FilesSources is not stripped
        assert get_stripped_files_for_sources_field(
            source_files=["f1.py"], sources_field_cls=FilesSources,
        ) == ([f"{source_root}/f1.py"], {})

        # When given `specified_files_snapshot`, only strip what is specified, even if that snapshot
        # has files not belonging to the corresponding Sources field! (Validation of ownership
        # would have a performance cost.)
        assert get_stripped_files_for_sources_field(
            source_files=["f1.py"], specified_source_files=["f1.py", "different_owner.py"],
        ) == (
            ["project/different_owner.py", "project/f1.py"],
            {"src/python": ("project/different_owner.py", "project/f1.py")},
        )

    def test_get_file_to_stripped_file_mapping(self) -> None:
        def get_stripped_file_mapping(
            paths: List[str], args: Optional[List[str]] = None
        ) -> Dict[str, str]:
            args = args or []
            args.append("--source-root-patterns=src/python")
            args.append("--source-root-patterns=src/java")
            request = StripSnapshotRequest(self.make_snapshot_of_empty_files(paths))
            result = self.request_single_product(
                SourceRootStrippedSources, Params(request, create_options_bootstrapper(args=args)),
            )
            return dict(result.get_file_to_stripped_file_mapping())

        assert get_stripped_file_mapping(["src/python/project/example.py"]) == {
            "src/python/project/example.py": "project/example.py"
        }
        assert get_stripped_file_mapping(
            ["src/python/project/example.py", "src/java/com/project/example.java"]
        ) == {
            "src/python/project/example.py": "project/example.py",
            "src/java/com/project/example.java": "com/project/example.java",
        }

        source_root_config = [f"--source-root-patterns={json.dumps(['/'])}"]
        assert get_stripped_file_mapping(
            ["project/f1.py", "project/f2.py"], args=source_root_config
        ) == {"project/f1.py": "project/f1.py", "project/f2.py": "project/f2.py",}
        assert get_stripped_file_mapping([]) == {}
