# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from pathlib import PurePath
from typing import Iterable, List, NamedTuple, Type

from pants.core.target_types import FilesSources
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.target import Sources as SourcesField
from pants.testutil.engine.util import Params
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class TargetSources(NamedTuple):
    source_root: str
    source_files: List[str]

    @property
    def full_paths(self) -> List[str]:
        return [PurePath(self.source_root, name).as_posix() for name in self.source_files]


SOURCES1 = TargetSources("src/python", ["s1.py", "s2.py", "s3.py"])
SOURCES2 = TargetSources("tests/python", ["t1.py", "t2.java"])
SOURCES3 = TargetSources("src/java", ["j1.java", "j2.java"])


class SourceFilesTest(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), *source_files_rules())

    def mock_sources_field(
        self,
        sources: TargetSources,
        *,
        include_sources: bool = True,
        sources_field_cls: Type[SourcesField] = SourcesField,
    ) -> SourcesField:
        sources_field = sources_field_cls(
            sources.source_files if include_sources else [],
            address=Address.parse(f"{sources.source_root}:lib"),
        )
        self.create_files(path=sources.source_root, files=sources.source_files)
        return sources_field

    def assert_sources_resolved(
        self,
        sources_fields: Iterable[SourcesField],
        *,
        expected: Iterable[TargetSources],
        expected_unrooted: Iterable[str] = (),
    ) -> None:
        result = self.request_single_product(
            SourceFiles, Params(SourceFilesRequest(sources_fields), create_options_bootstrapper()),
        )
        assert list(result.snapshot.files) == sorted(
            set(itertools.chain.from_iterable(sources.full_paths for sources in expected))
        )
        assert list(result.unrooted_files) == sorted(expected_unrooted)

    def test_address_specs(self) -> None:
        sources_field1 = self.mock_sources_field(SOURCES1)
        sources_field2 = self.mock_sources_field(SOURCES2)
        sources_field3 = self.mock_sources_field(SOURCES3)
        sources_field4 = self.mock_sources_field(SOURCES1)

        self.assert_sources_resolved([sources_field1], expected=[SOURCES1])
        self.assert_sources_resolved([sources_field2], expected=[SOURCES2])
        self.assert_sources_resolved([sources_field3], expected=[SOURCES3])
        self.assert_sources_resolved([sources_field4], expected=[SOURCES1])

        # NB: sources_field1 and sources_field4 refer to the same files. We should be able to
        # handle this gracefully.
        self.assert_sources_resolved(
            [sources_field1, sources_field2, sources_field3, sources_field4],
            expected=[SOURCES1, SOURCES2, SOURCES3],
        )

    def test_file_sources(self) -> None:
        sources = TargetSources("src/python", ["README.md"])
        field = self.mock_sources_field(sources, sources_field_cls=FilesSources)
        self.assert_sources_resolved(
            [field], expected=[sources], expected_unrooted=sources.full_paths
        )

    def test_gracefully_handle_no_sources(self) -> None:
        sources_field = self.mock_sources_field(SOURCES1, include_sources=False)
        self.assert_sources_resolved([sources_field], expected=[])
