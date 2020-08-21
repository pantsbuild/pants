# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from typing import Iterator

from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.testutil.pants_integration_test import PantsIntegrationTest


class GraphIntegrationTest(PantsIntegrationTest):
    @classmethod
    def use_pantsd_env_var(cls):
        """Some of the tests here expect to read the standard error after an intentional failure.

        However, when pantsd is enabled, these errors are logged to logs/exceptions.<pid>.log So
        stderr appears empty. (see #7320)
        """
        return False

    _NO_BUILD_FILE_TARGET_BASE = "testprojects/src/python/no_build_file"
    _SOURCES_TARGET_BASE = "testprojects/src/python/sources"

    _ERR_TARGETS = {
        "testprojects/src/python/sources:some-missing-some-not": [
            "['*.txt', '*.rs']",
            "Snapshot(PathGlobs(globs=('testprojects/src/python/sources/*.txt', 'testprojects/src/python/sources/*.rs'), glob_match_error_behavior<Exactly(GlobMatchErrorBehavior)>=GlobMatchErrorBehavior(value=error), conjunction<Exactly(GlobExpansionConjunction)>=GlobExpansionConjunction(value=all_match)))",
            'Unmatched glob from testprojects/src/python/sources:some-missing-some-not\'s `sources` field: "testprojects/src/python/sources/*.rs"',
        ],
        "testprojects/src/python/sources:missing-sources": [
            "*.scala",
            "Snapshot(PathGlobs(globs=('testprojects/src/python/sources/*.scala', '!testprojects/src/python/sources/*Test.scala', '!testprojects/src/python/sources/*Spec.scala'), glob_match_error_behavior<Exactly(GlobMatchErrorBehavior)>=GlobMatchErrorBehavior(value=error), conjunction<Exactly(GlobExpansionConjunction)>=GlobExpansionConjunction(value=any_match)))",
            'Unmatched glob from testprojects/src/python/sources:missing-sources\'s `sources` field:: "testprojects/src/python/sources/*.scala", excludes: ["testprojects/src/python/sources/*Test.scala", "testprojects/src/python/sources/*Spec.scala"]',
        ],
    }

    @contextmanager
    def setup_sources_targets(self) -> Iterator[None]:
        build_path = Path(self._SOURCES_TARGET_BASE, "BUILD")
        original_content = build_path.read_text()
        new_content = dedent(
            """\
            scala_library(
              name='missing-sources',
            )

            resources(
              name='missing-literal-files',
              sources=[
                'nonexistent_test_file.txt',
                'another_nonexistent_file.txt',
              ],
            )

            resources(
              name='missing-globs',
              sources=['*.a'],
            )

            resources(
              name='missing-rglobs',
              sources=['**/*.a'],
            )

            resources(
              name='some-missing-some-not',
              sources=['*.txt', '*.rs'],
            )

            resources(
              name='overlapping-globs',
              sources=['sources.txt', '*.txt'],
            )
            """
        )
        with self.with_overwritten_file_content(build_path, f"{original_content}\n{new_content}"):
            yield

    @unittest.skip("flaky: https://github.com/pantsbuild/pants/issues/8520")
    def test_missing_sources_warnings(self):
        target_to_unmatched_globs = {
            "missing-globs": ["*.a"],
            "missing-rglobs": ["**/*.a"],
            "missing-literal-files": ["another_nonexistent_file.txt", "nonexistent_test_file.txt"],
        }
        with self.setup_sources_targets():
            for target in target_to_unmatched_globs:
                target_full = f"{self._SOURCES_TARGET_BASE}:{target}"
                pants_run = self.run_pants(
                    ["filedeps", target_full],
                    config={GLOBAL_SCOPE_CONFIG_SECTION: {"files_not_found_behavior": "warn"}},
                )
                self.assert_success(pants_run)
                unmatched_globs = target_to_unmatched_globs[target]
                formatted_globs = ", ".join(
                    f'"{os.path.join(self._SOURCES_TARGET_BASE, glob)}"' for glob in unmatched_globs
                )
                error_origin = f"from {self._SOURCES_TARGET_BASE}:{target}'s `sources` field"
                if len(unmatched_globs) == 1:
                    assert (
                        f"[WARN] Unmatched glob {error_origin}: {formatted_globs}"
                        in pants_run.stderr
                    )
                else:
                    assert (
                        f"[WARN] Unmatched globs {error_origin}: [{formatted_globs}]"
                        in pants_run.stderr
                    )

    @unittest.skip("flaky: https://github.com/pantsbuild/pants/issues/8520")
    def test_existing_sources(self):
        target_full = f"{self._SOURCES_TARGET_BASE}:text"
        pants_run = self.run_pants(
            ["filedeps", target_full],
            config={GLOBAL_SCOPE_CONFIG_SECTION: {"files_not_found_behavior": "warn"}},
        )
        self.assert_success(pants_run)
        assert "[WARN] Unmatched glob" not in pants_run.stderr

    def test_existing_directory_with_no_build_files_fails(self):
        pants_run = self.run_pants(["list", f"{self._NO_BUILD_FILE_TARGET_BASE}::"])
        self.assert_failure(pants_run)
        self.assertIn("does not match any targets.", pants_run.stderr)

    @unittest.skip("flaky: https://github.com/pantsbuild/pants/issues/6787")
    def test_error_message(self):
        with self.setup_sources_targets():
            for target in self._ERR_TARGETS:
                expected_excerpts = self._ERR_TARGETS[target]
                pants_run = self.run_pants(
                    ["filedeps", target],
                    config={GLOBAL_SCOPE_CONFIG_SECTION: {"files_not_found_behavior": "error"}},
                )
                self.assert_failure(pants_run)
                for excerpt in expected_excerpts:
                    self.assertIn(excerpt, pants_run.stderr)
