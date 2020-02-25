# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import Iterable, List, NamedTuple, Optional
from unittest.mock import Mock

from pants.base.specs import (
    AscendantAddresses,
    DescendantAddresses,
    FilesystemLiteralSpec,
    FilesystemResolvedGlobSpec,
    OriginSpec,
    SiblingAddresses,
    SingleAddress,
)
from pants.build_graph.address import Address
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.determine_specified_source_files import (
    SpecifiedSourceFiles,
    SpecifiedSourceFilesRequest,
)
from pants.rules.core.determine_specified_source_files import rules as determine_source_files_rules
from pants.rules.core.strip_source_roots import rules as strip_source_roots_rules
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class TargetSources(NamedTuple):
    source_root: str
    source_files: List[str]

    @property
    def source_file_absolute_paths(self) -> List[str]:
        return [PurePath(self.source_root, name).as_posix() for name in self.source_files]


class DetermineSpecifiedSourceFilesTest(TestBase):

    SOURCES1 = TargetSources("src/python", ["s1.py", "s2.py", "s3.py"])
    SOURCES2 = TargetSources("tests/python", ["t1.py", "t2.java"])
    SOURCES3 = TargetSources("src/java", ["j1.java", "j2.java"])

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *determine_source_files_rules(),
            *strip_source_roots_rules(),
            RootRule(SpecifiedSourceFilesRequest),
        )

    def mock_target(
        self, sources: TargetSources, *, origin: Optional[OriginSpec] = None
    ) -> TargetAdaptorWithOrigin:
        adaptor = Mock()
        adaptor.sources = Mock()
        adaptor.address = Address.parse(f"{sources.source_root}:lib")
        adaptor.sources.snapshot = self.make_snapshot(
            {fp: "" for fp in sources.source_file_absolute_paths}
        )
        if origin is None:
            origin = SiblingAddresses(sources.source_root)
        return TargetAdaptorWithOrigin(adaptor, origin)

    def get_source_files(
        self,
        adaptors_with_origins: Iterable[TargetAdaptorWithOrigin],
        *,
        strip_source_roots: bool = False,
    ) -> List[str]:
        request = SpecifiedSourceFilesRequest(
            adaptors_with_origins, strip_source_roots=strip_source_roots,
        )
        result = self.request_single_product(
            SpecifiedSourceFiles, Params(request, create_options_bootstrapper())
        )
        return sorted(result.snapshot.files)

    def test_address_specs(self) -> None:
        target1 = self.mock_target(
            self.SOURCES1, origin=SingleAddress(directory=self.SOURCES1.source_root, name="lib")
        )
        target2 = self.mock_target(
            self.SOURCES2, origin=SiblingAddresses(self.SOURCES2.source_root)
        )
        target3 = self.mock_target(
            self.SOURCES3, origin=DescendantAddresses(self.SOURCES3.source_root)
        )
        target4 = self.mock_target(
            self.SOURCES1, origin=AscendantAddresses(self.SOURCES1.source_root)
        )
        assert self.get_source_files([target1]) == self.SOURCES1.source_file_absolute_paths
        assert self.get_source_files([target2]) == self.SOURCES2.source_file_absolute_paths
        assert self.get_source_files([target3]) == self.SOURCES3.source_file_absolute_paths
        assert self.get_source_files([target4]) == self.SOURCES1.source_file_absolute_paths
        # NB: target1 and target4 refer to the same files. We should be able to handle this
        # gracefully.
        assert self.get_source_files([target1, target2, target3, target4]) == sorted(
            [
                *self.SOURCES1.source_file_absolute_paths,
                *self.SOURCES2.source_file_absolute_paths,
                *self.SOURCES3.source_file_absolute_paths,
            ]
        )

    def test_filesystem_specs(self) -> None:
        # Literal file arg.
        target1_expected = self.SOURCES1.source_file_absolute_paths[0]
        target1 = self.mock_target(self.SOURCES1, origin=FilesystemLiteralSpec(target1_expected))

        # Glob file arg that matches the entire target's `sources`.
        target2_expected = self.SOURCES2.source_file_absolute_paths
        target2_origin = FilesystemResolvedGlobSpec(
            f"{self.SOURCES2.source_root}/*.py",
            _snapshot=self.make_snapshot_of_empty_files(target2_expected),
        )
        target2 = self.mock_target(self.SOURCES2, origin=target2_origin)

        # Glob file arg that only matches a subset of the target's `sources` _and_ includes resolved
        # files not owned by the target.
        target3_expected = self.SOURCES3.source_file_absolute_paths[0]
        target3_origin = FilesystemResolvedGlobSpec(
            f"{self.SOURCES3.source_root}/*.java",
            _snapshot=self.make_snapshot_of_empty_files(
                [
                    PurePath(self.SOURCES3.source_root, name).as_posix()
                    for name in [self.SOURCES3.source_files[0], "other_target.java", "j.tmp.java",]
                ]
            ),
        )
        target3 = self.mock_target(self.SOURCES3, origin=target3_origin)

        assert self.get_source_files([target1]) == [target1_expected]
        assert self.get_source_files([target2]) == target2_expected
        assert self.get_source_files([target3]) == [target3_expected]
        assert self.get_source_files([target1, target2, target3]) == sorted(
            [target1_expected, *target2_expected, target3_expected]
        )

    def test_strip_source_roots(self) -> None:
        target1 = self.mock_target(self.SOURCES1)
        target2 = self.mock_target(self.SOURCES2)
        target3 = self.mock_target(self.SOURCES3)

        def assert_source_roots_stripped(
            target: TargetAdaptorWithOrigin, sources: TargetSources
        ) -> None:
            assert self.get_source_files([target], strip_source_roots=True) == sources.source_files

        assert_source_roots_stripped(target1, self.SOURCES1)
        assert_source_roots_stripped(target2, self.SOURCES2)
        assert_source_roots_stripped(target3, self.SOURCES3)
        assert self.get_source_files(
            [target1, target2, target3], strip_source_roots=True
        ) == sorted(
            [*self.SOURCES1.source_files, *self.SOURCES2.source_files, *self.SOURCES3.source_files]
        )
