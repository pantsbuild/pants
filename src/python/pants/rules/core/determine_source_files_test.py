# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import List
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
from pants.rules.core.determine_source_files import DetermineSourceFilesRequest, SourceFiles
from pants.rules.core.determine_source_files import rules as determine_source_files_rules
from pants.rules.core.strip_source_roots import rules as strip_source_roots_rules
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class DetermineSourceFilesTest(TestBase):

    SOURCE_ROOT = "src/python"
    TARGET_SOURCES = [
        PurePath("src/python", name).as_posix() for name in ["f1.py", "f2.py", "f3.py"]
    ]

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *determine_source_files_rules(),
            *strip_source_roots_rules(),
            RootRule(DetermineSourceFilesRequest),
        )

    def get_target_source_files(
        self, *, origin: OriginSpec, strip_source_roots: bool = False,
    ) -> List[str]:
        adaptor = Mock()
        adaptor.sources = Mock()
        adaptor.address = Address.parse(f"{self.SOURCE_ROOT}:lib")
        adaptor.sources.snapshot = self.make_snapshot({fp: "" for fp in self.TARGET_SOURCES})
        request = DetermineSourceFilesRequest(
            TargetAdaptorWithOrigin(adaptor, origin), strip_source_roots=strip_source_roots,
        )
        result = self.request_single_product(
            SourceFiles, Params(request, create_options_bootstrapper())
        )
        return sorted(result.snapshot.files)

    def test_address_specs(self) -> None:
        for origin in [
            SingleAddress(directory=self.SOURCE_ROOT, name="lib"),
            SiblingAddresses(self.SOURCE_ROOT),
            DescendantAddresses(self.SOURCE_ROOT),
            AscendantAddresses(self.SOURCE_ROOT),
        ]:
            assert self.get_target_source_files(origin=origin) == self.TARGET_SOURCES

    def test_filesystem_specs(self) -> None:
        literal_spec = FilesystemLiteralSpec(self.TARGET_SOURCES[0])
        assert self.get_target_source_files(origin=literal_spec) == [self.TARGET_SOURCES[0]]

        # Test when a file glob includes resolved files not owned by the target.
        glob_spec = FilesystemResolvedGlobSpec(
            f"{self.SOURCE_ROOT}/*.py",
            _snapshot=self.make_snapshot(
                {
                    fp: ""
                    for fp in [
                        PurePath(self.SOURCE_ROOT, name).as_posix()
                        for name in ["f1.py", "f4.py", "f5.py"]
                    ]
                }
            ),
        )
        assert self.get_target_source_files(origin=glob_spec) == [self.TARGET_SOURCES[0]]

    def test_strip_source_roots(self) -> None:
        assert self.get_target_source_files(
            origin=SiblingAddresses(self.SOURCE_ROOT), strip_source_roots=True,
        ) == ["f1.py", "f2.py", "f3.py"]
