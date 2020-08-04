# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from typing import Iterable, List, NamedTuple, Optional, Tuple, Type

from pants.base.specs import (
    AscendantAddresses,
    DescendantAddresses,
    FilesystemLiteralSpec,
    FilesystemResolvedGlobSpec,
    OriginSpec,
    SiblingAddresses,
    SingleAddress,
)
from pants.core.target_types import FilesSources
from pants.core.util_rules.determine_source_files import (
    AllSourceFilesRequest,
    SourceFiles,
    SpecifiedSourceFilesRequest,
)
from pants.core.util_rules.determine_source_files import rules as determine_source_files_rules
from pants.engine.addresses import Address
from pants.engine.target import Sources as SourcesField
from pants.testutil.engine.util import Params
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class TargetSources(NamedTuple):
    source_root: str
    source_files: List[str]

    @property
    def source_file_absolute_paths(self) -> List[str]:
        return [PurePath(self.source_root, name).as_posix() for name in self.source_files]


SOURCES1 = TargetSources("src/python", ["s1.py", "s2.py", "s3.py"])
SOURCES2 = TargetSources("tests/python", ["t1.py", "t2.java"])
SOURCES3 = TargetSources("src/java", ["j1.java", "j2.java"])
SOURCES4 = TargetSources("src/python", ["README.md"])


class DetermineSourceFilesTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *determine_source_files_rules(),
        )

    def mock_sources_field_with_origin(
        self,
        sources: TargetSources,
        *,
        origin: Optional[OriginSpec] = None,
        include_sources: bool = True,
        sources_field_cls: Type[SourcesField] = SourcesField,
    ) -> Tuple[SourcesField, OriginSpec]:
        sources_field = sources_field_cls(
            sources.source_files if include_sources else [],
            address=Address.parse(f"{sources.source_root}:lib"),
        )
        self.create_files(path=sources.source_root, files=sources.source_files)
        if origin is None:
            origin = SiblingAddresses(sources.source_root)
        return sources_field, origin

    def _do_get_all_source_files(
        self, sources_fields_with_origins: Iterable[Tuple[SourcesField, OriginSpec]],
    ) -> SourceFiles:
        request = AllSourceFilesRequest(
            (
                sources_field_with_origin[0]
                for sources_field_with_origin in sources_fields_with_origins
            ),
        )
        return self.request_single_product(
            SourceFiles,
            Params(
                request,
                create_options_bootstrapper(
                    args=[
                        "--source-root-patterns=src/python",
                        "--source-root-patterns=src/java",
                        "--source-root-patterns=tests/python",
                    ]
                ),
            ),
        )

    def get_all_source_files(
        self, sources_fields_with_origins: Iterable[Tuple[SourcesField, OriginSpec]],
    ) -> List[str]:
        return sorted(self._do_get_all_source_files(sources_fields_with_origins).snapshot.files)

    def get_all_unrooted_files(
        self, sources_fields_with_origins: Iterable[Tuple[SourcesField, OriginSpec]]
    ):
        return list(self._do_get_all_source_files(sources_fields_with_origins).unrooted_files)

    def _do_get_specified_source_files(
        self, sources_fields_with_origins: Iterable[Tuple[SourcesField, OriginSpec]],
    ) -> SourceFiles:
        request = SpecifiedSourceFilesRequest(sources_fields_with_origins,)
        return self.request_single_product(
            SourceFiles,
            Params(
                request,
                create_options_bootstrapper(
                    args=[
                        "--source-root-patterns=src/python",
                        "--source-root-patterns=src/java",
                        "--source-root-patterns=tests/python",
                    ]
                ),
            ),
        )

    def get_specified_source_files(
        self, sources_fields_with_origins: Iterable[Tuple[SourcesField, OriginSpec]],
    ) -> List[str]:
        return sorted(
            self._do_get_specified_source_files(sources_fields_with_origins).snapshot.files
        )

    def get_specified_unrooted_files(
        self, sources_fields_with_origins: Iterable[Tuple[SourcesField, OriginSpec]]
    ):
        return list(self._do_get_specified_source_files(sources_fields_with_origins).unrooted_files)

    def test_address_specs(self) -> None:
        sources_field1 = self.mock_sources_field_with_origin(
            SOURCES1, origin=SingleAddress(directory=SOURCES1.source_root, name="lib")
        )
        sources_field2 = self.mock_sources_field_with_origin(
            SOURCES2, origin=SiblingAddresses(SOURCES2.source_root)
        )
        sources_field3 = self.mock_sources_field_with_origin(
            SOURCES3, origin=DescendantAddresses(SOURCES3.source_root)
        )
        sources_field4 = self.mock_sources_field_with_origin(
            SOURCES1, origin=AscendantAddresses(SOURCES1.source_root)
        )

        def assert_all_source_files_resolved(
            sources_field_with_origin: Tuple[SourcesField, OriginSpec], sources: TargetSources
        ) -> None:
            expected = sources.source_file_absolute_paths
            assert self.get_all_source_files([sources_field_with_origin]) == expected
            assert self.get_specified_source_files([sources_field_with_origin]) == expected

        assert_all_source_files_resolved(sources_field1, SOURCES1)
        assert_all_source_files_resolved(sources_field2, SOURCES2)
        assert_all_source_files_resolved(sources_field3, SOURCES3)
        assert_all_source_files_resolved(sources_field4, SOURCES1)
        # NB: sources_field1 and sources_field4 refer to the same files. We should be able to
        # handle this gracefully.
        combined_sources_fields = [sources_field1, sources_field2, sources_field3, sources_field4]
        combined_expected = sorted(
            [
                *SOURCES1.source_file_absolute_paths,
                *SOURCES2.source_file_absolute_paths,
                *SOURCES3.source_file_absolute_paths,
            ]
        )
        assert self.get_all_source_files(combined_sources_fields) == combined_expected
        assert self.get_all_unrooted_files(combined_sources_fields) == []
        assert self.get_specified_source_files(combined_sources_fields) == combined_expected
        assert self.get_specified_unrooted_files(combined_sources_fields) == []

    def test_filesystem_specs(self) -> None:
        # Literal file arg.
        sources_field1_all_sources = SOURCES1.source_file_absolute_paths
        sources_field1_slice = slice(0, 1)
        sources_field1 = self.mock_sources_field_with_origin(
            SOURCES1, origin=FilesystemLiteralSpec(sources_field1_all_sources[0])
        )

        # Glob file arg that matches the entire `sources`.
        sources_field2_all_sources = SOURCES2.source_file_absolute_paths
        sources_field2_slice = slice(0, len(sources_field2_all_sources))
        sources_field2_origin = FilesystemResolvedGlobSpec(
            f"{SOURCES2.source_root}/*.py", files=tuple(sources_field2_all_sources)
        )
        sources_field2 = self.mock_sources_field_with_origin(SOURCES2, origin=sources_field2_origin)

        # Glob file arg that only matches a subset of the `sources` _and_ includes resolved
        # files not owned by the target.
        sources_field3_all_sources = SOURCES3.source_file_absolute_paths
        sources_field3_slice = slice(0, 1)
        sources_field3_origin = FilesystemResolvedGlobSpec(
            f"{SOURCES3.source_root}/*.java",
            files=tuple(
                PurePath(SOURCES3.source_root, name).as_posix()
                for name in [SOURCES3.source_files[0], "other_target.java", "j.tmp.java"]
            ),
        )
        sources_field3 = self.mock_sources_field_with_origin(SOURCES3, origin=sources_field3_origin)

        # FilesSources should appear in the "all_source_files" results but not in the
        # "all_rooted_files" results.
        sources_field4 = self.mock_sources_field_with_origin(
            SOURCES4, sources_field_cls=FilesSources
        )
        sources_field4_all_sources = SOURCES4.source_file_absolute_paths

        def assert_file_args_resolved(
            sources_field_with_origin: Tuple[SourcesField, OriginSpec],
            all_sources: List[str],
            expected_slice: slice,
        ) -> None:
            assert self.get_all_source_files([sources_field_with_origin]) == all_sources
            assert self.get_all_unrooted_files([sources_field_with_origin]) == []

            assert (
                self.get_specified_source_files([sources_field_with_origin])
                == all_sources[expected_slice]
            )
            assert self.get_specified_unrooted_files([sources_field_with_origin]) == []

        assert_file_args_resolved(sources_field1, sources_field1_all_sources, sources_field1_slice)
        assert_file_args_resolved(sources_field2, sources_field2_all_sources, sources_field2_slice)
        assert_file_args_resolved(sources_field3, sources_field3_all_sources, sources_field3_slice)

        combined_sources_fields = [sources_field1, sources_field2, sources_field3, sources_field4]
        assert self.get_all_source_files(combined_sources_fields) == sorted(
            [
                *sources_field1_all_sources,
                *sources_field2_all_sources,
                *sources_field3_all_sources,
                *sources_field4_all_sources,
            ]
        )
        assert self.get_all_unrooted_files(combined_sources_fields) == sorted(
            [*sources_field4_all_sources]
        )

        assert self.get_specified_source_files(combined_sources_fields) == sorted(
            [
                *sources_field1_all_sources[sources_field1_slice],
                *sources_field2_all_sources[sources_field2_slice],
                *sources_field3_all_sources[sources_field3_slice],
                *sources_field4_all_sources,
            ]
        )

        assert self.get_specified_unrooted_files(combined_sources_fields) == sorted(
            [*sources_field4_all_sources,]
        )

    def test_gracefully_handle_no_sources(self) -> None:
        sources_field = self.mock_sources_field_with_origin(SOURCES1, include_sources=False)
        assert self.get_all_source_files([sources_field]) == []
        assert self.get_specified_source_files([sources_field]) == []
        assert self.get_all_unrooted_files([sources_field]) == []
        assert self.get_specified_unrooted_files([sources_field]) == []
