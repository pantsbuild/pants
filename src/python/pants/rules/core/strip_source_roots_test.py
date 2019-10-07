# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from unittest.mock import Mock

from pants.build_graph.files import Files
from pants.engine.fs import create_fs_rules
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.strip_source_root import SourceRootStrippedSources, strip_source_root
from pants.source.source_root import SourceRootConfig
from pants_test.subsystem.subsystem_util import init_subsystem
from pants_test.test_base import TestBase


class StripSourceRootsTests(TestBase):
    @classmethod
    def rules(cls):
        return (
            super().rules()
            + [strip_source_root, RootRule(SourceRootConfig), RootRule(HydratedTarget)]
            + create_fs_rules()
        )

    def assert_stripped_source_file(
        self, *, original_path: str, expected_path: str, target_type_alias=None
    ):
        init_subsystem(SourceRootConfig)
        adaptor = Mock()
        adaptor.sources = Mock()
        source_files = {original_path: "print('random python')"}
        adaptor.sources.snapshot = self.make_snapshot(source_files)
        adaptor.address = Mock()
        adaptor.address.spec_path = original_path
        if target_type_alias:
            adaptor.type_alias = target_type_alias
        target = HydratedTarget("some/target/address", adaptor, tuple())
        output = self.scheduler.product_request(
            SourceRootStrippedSources, [Params(target, SourceRootConfig.global_instance())]
        )
        stripped_sources = output[0]
        self.assertEqual(stripped_sources.snapshot.files, (expected_path,))

    def test_source_roots_python(self):
        self.assert_stripped_source_file(
            original_path="src/python/pants/util/strutil.py", expected_path="pants/util/strutil.py"
        )

    def test_source_roots_java(self):
        self.assert_stripped_source_file(
            original_path="src/java/some/path/to/something.java",
            expected_path="some/path/to/something.java",
        )

    def test_dont_strip_source_for_files(self):
        self.assert_stripped_source_file(
            original_path="src/python/pants/util/strutil.py",
            expected_path="src/python/pants/util/strutil.py",
            target_type_alias=Files.alias(),
        )
