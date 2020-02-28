# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.task.unpack_remote_sources_base import UnpackRemoteSourcesBase
from pants.testutil.test_base import TestBase


class UnpackRemoteSourcesTest(TestBase):
    """Test common functionality for tasks unpacking remote sources, including file filtering."""

    def test_invalid_pattern(self):
        with self.assertRaises(UnpackRemoteSourcesBase.InvalidPatternError):
            UnpackRemoteSourcesBase.compile_patterns([45])

    @staticmethod
    def _run_filter(filename, include_patterns=None, exclude_patterns=None):
        return UnpackRemoteSourcesBase._file_filter(
            filename,
            UnpackRemoteSourcesBase.compile_patterns(include_patterns or []),
            UnpackRemoteSourcesBase.compile_patterns(exclude_patterns or []),
        )

    def test_file_filter(self):
        # If no patterns are specified, everything goes through
        self.assertTrue(self._run_filter("foo/bar.java"))

        self.assertTrue(self._run_filter("foo/bar.java", include_patterns=["**/*.java"]))
        self.assertTrue(self._run_filter("bar.java", include_patterns=["**/*.java"]))
        self.assertTrue(self._run_filter("bar.java", include_patterns=["**/*.java", "*.java"]))
        self.assertFalse(self._run_filter("foo/bar.java", exclude_patterns=["**/bar.*"]))
        self.assertFalse(
            self._run_filter(
                "foo/bar.java", include_patterns=["**/*/java"], exclude_patterns=["**/bar.*"]
            )
        )

        # exclude patterns should be computed before include patterns
        self.assertFalse(
            self._run_filter(
                "foo/bar.java", include_patterns=["foo/*.java"], exclude_patterns=["foo/b*.java"]
            )
        )
        self.assertTrue(
            self._run_filter(
                "foo/bar.java", include_patterns=["foo/*.java"], exclude_patterns=["foo/x*.java"]
            )
        )

        # Validate that trailing globs match both the empty string and non-empty strings.
        self.assertTrue(self._run_filter("foo.so", include_patterns=["*.so"]))
        self.assertTrue(self._run_filter("foo.so", include_patterns=["*.so*"]))
        self.assertTrue(self._run_filter("foo.so.1", include_patterns=["*.so*"]))

    @unittest.expectedFailure
    def test_problematic_cases(self):
        """These should pass, but don't."""
        # See https://github.com/twitter/commons/issues/380.  'foo*bar' doesn't match 'foobar'
        self.assertFalse(
            self._run_filter(
                "foo/bar.java", include_patterns=["foo/*.java"], exclude_patterns=["foo/bar*.java"]
            )
        )
