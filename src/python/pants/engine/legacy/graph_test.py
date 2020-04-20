# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import os
from typing import cast

from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.files import Files
from pants.testutil.test_base import TestBase


# Macro that adds the specified tag.
def macro(target_cls, tag, parse_context, tags=None, **kwargs):
    tags = tags or set()
    tags.add(tag)
    parse_context.create_object(target_cls, tags=tags, **kwargs)


class GraphTest(TestBase):

    _TAG = "tag_added_by_macro"

    @classmethod
    def alias_groups(cls) -> BuildFileAliases:
        return cast(
            BuildFileAliases,
            super()
            .alias_groups()
            .merge(
                BuildFileAliases(
                    targets={
                        "files": Files,
                        "tagged_files": TargetMacro.Factory.wrap(
                            functools.partial(macro, Files, cls._TAG), Files
                        ),
                    }
                )
            ),
        )

    def test_with_missing_target_in_existing_build_file(self) -> None:
        self.create_library(path="3rdparty/python", target_type="target", name="Markdown")
        self.create_library(path="3rdparty/python", target_type="target", name="Pygments")
        # When a target is missing,
        #  the suggestions should be in order
        #  and there should only be one copy of the error if tracing is off.
        expected_message = (
            '"rutabaga" was not found in namespace "3rdparty/python".'
            ".*Did you mean one of:\n"
            ".*:Markdown\n"
            ".*:Pygments\n"
        )
        with self.assertRaisesRegex(AddressLookupError, expected_message):
            self.targets("3rdparty/python:rutabaga")

    def test_with_missing_directory_fails(self) -> None:
        with self.assertRaises(AddressLookupError) as cm:
            self.targets("no-such-path:")

        self.assertIn('Path "no-such-path" does not contain any BUILD files', str(cm.exception))

    def test_invalidate_fsnode(self) -> None:
        # NB: Invalidation is now more directly tested in unit tests in the `graph` crate.
        self.create_library(path="src/example", target_type="target", name="things")
        self.targets("src/example::")
        invalidated_count = self.invalidate_for("src/example/BUILD")
        self.assertGreater(invalidated_count, 0)

    def test_sources_ordering(self) -> None:
        input_sources = ["p", "a", "n", "t", "s", "b", "u", "i", "l", "d"]
        expected_sources = sorted(input_sources)
        self.create_library(
            path="src/example", target_type="files", name="things", sources=input_sources
        )

        target = self.target("src/example:things")
        sources = [os.path.basename(s) for s in target.sources_relative_to_buildroot()]
        self.assertEqual(expected_sources, sources)

    def test_target_macro_override(self) -> None:
        """Tests that we can "wrap" an existing target type with additional functionality.

        Installs an additional TargetMacro that wraps `target` aliases to add a tag to all
        definitions.
        """

        files = self.create_library(path="src/example", target_type="tagged_files", name="things")
        self.assertIn(self._TAG, files.tags)
        self.assertEqual(type(files), Files)
