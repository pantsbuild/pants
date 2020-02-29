# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import List, Optional, Union
from unittest.mock import Mock

import pytest

from pants.build_graph.address import Address
from pants.build_graph.files import Files
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.scheduler import ExecutionError
from pants.engine.selectors import Params
from pants.rules.core.strip_source_roots import (
    SourceRootStrippedSources,
    StripSnapshotRequest,
    StripTargetRequest,
)
from pants.rules.core.strip_source_roots import rules as strip_source_root_rules
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class StripSourceRootsTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *strip_source_root_rules(),
        )

    def get_stripped_files(
        self,
        request: Union[StripSnapshotRequest, StripTargetRequest],
        *,
        args: Optional[List[str]] = None,
    ) -> List[str]:
        result = self.request_single_product(
            SourceRootStrippedSources, Params(request, create_options_bootstrapper(args=args))
        )
        return sorted(result.snapshot.files)

    def test_strip_snapshot(self) -> None:
        def get_stripped_files_for_snapshot(
            paths: List[str],
            *,
            use_representative_path: bool = True,
            args: Optional[List[str]] = None,
        ) -> List[str]:
            input_snapshot = self.make_snapshot({fp: "" for fp in paths})
            request = StripSnapshotRequest(
                input_snapshot, representative_path=paths[0] if use_representative_path else None
            )
            return self.get_stripped_files(request, args=args)

        # Normal source roots
        assert get_stripped_files_for_snapshot(["src/python/project/example.py"]) == [
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
        assert get_stripped_files_for_snapshot([unrecognized_source_root]) == ["example.txt"]
        with pytest.raises(ExecutionError) as exc:
            get_stripped_files_for_snapshot(
                [unrecognized_source_root], args=["--source-unmatched=fail"]
            )
        assert (
            f"NoSourceRootError: Could not find a source root for `{unrecognized_source_root}`"
            in str(exc.value)
        )

        # Support for multiple source roots
        file_names = ["src/python/project/example.py", "src/java/com/project/example.java"]
        with pytest.raises(ExecutionError) as exc:
            get_stripped_files_for_snapshot(file_names, use_representative_path=True)
        assert "Cannot strip prefix src/python" in str(exc.value)
        assert sorted(
            get_stripped_files_for_snapshot(file_names, use_representative_path=False)
        ) == sorted(["project/example.py", "com/project/example.java"])

    def test_strip_target(self) -> None:
        def get_stripped_files_for_target(
            *,
            source_paths: Optional[List[str]],
            type_alias: Optional[str] = None,
            specified_sources: Optional[List[str]] = None,
        ) -> List[str]:
            address = (
                Address(spec_path=PurePath(source_paths[0]).parent.as_posix(), target_name="target")
                if source_paths
                else Address.parse("src/python/project:target")
            )
            sources = Mock()
            sources.snapshot = self.make_snapshot_of_empty_files(source_paths or [])
            specified_sources_snapshot = (
                None
                if not specified_sources
                else self.make_snapshot_of_empty_files(specified_sources)
            )
            return self.get_stripped_files(
                StripTargetRequest(
                    TargetAdaptor(address=address, type_alias=type_alias, sources=sources),
                    specified_files_snapshot=specified_sources_snapshot,
                )
            )

        # normal target
        assert get_stripped_files_for_target(
            source_paths=["src/python/project/f1.py", "src/python/project/f2.py"]
        ) == sorted(["project/f1.py", "project/f2.py"])

        # empty target
        assert get_stripped_files_for_target(source_paths=None) == []

        # files targets are not stripped
        assert get_stripped_files_for_target(
            source_paths=["src/python/project/f1.py"], type_alias=Files.alias(),
        ) == ["src/python/project/f1.py"]

        # When given `specified_files_snapshot`, only strip what is specified, even if that snapshot
        # has files not belonging to the target! (Validation of ownership would be too costly.)
        assert get_stripped_files_for_target(
            source_paths=["src/python/project/f1.py"],
            specified_sources=["src/python/project/f1.py", "src/python/project/different_owner.py"],
        ) == sorted(["project/f1.py", "project/different_owner.py"])
