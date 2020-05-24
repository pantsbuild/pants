# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from typing import Iterator

from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class GraphIntegrationTest(PantsRunIntegrationTest):
    @classmethod
    def use_pantsd_env_var(cls):
        """Some of the tests here expect to read the standard error after an intentional failure.

        However, when pantsd is enabled, these errors are logged to logs/exceptions.<pid>.log So
        stderr appears empty. (see #7320)
        """
        return False

    _NO_BUILD_FILE_TARGET_BASE = "testprojects/src/python/no_build_file"

    _SOURCES_TARGET_BASE = "testprojects/src/python/sources"

    _BUNDLE_TARGET_BASE = "testprojects/src/java/org/pantsbuild/testproject/bundle"

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
        "testprojects/src/java/org/pantsbuild/testproject/bundle:missing-bundle-fileset": [
            "['a/b/file1.txt']",
            "['*.aaaa', '*.bbbb']",
            "['*.aaaa']",
            "['**/*.abab']",
            "['file1.aaaa', 'file2.aaaa']",
            "Snapshot(PathGlobs(globs=('testprojects/src/java/org/pantsbuild/testproject/bundle/*.aaaa',), glob_match_error_behavior<Exactly(GlobMatchErrorBehavior)>=GlobMatchErrorBehavior(value=error), conjunction<Exactly(GlobExpansionConjunction)>=GlobExpansionConjunction(value=all_match)))",
            'Unmatched glob from testprojects/src/java/org/pantsbuild/testproject/bundle:missing-bundle-fileset\'s `bundles` field:: "testprojects/src/java/org/pantsbuild/testproject/bundle/*.aaaa"',
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

    @contextmanager
    def setup_bundle_target(self) -> Iterator[None]:
        build_path = Path(self._BUNDLE_TARGET_BASE, "BUILD")
        original_content = build_path.read_text()
        new_content = dedent(
            """\
            jvm_app(
              name='missing-bundle-fileset',
              binary=':bundle-bin',
              bundles=[
                bundle(fileset=['a/b/file1.txt']),
                bundle(fileset=['**/*.aaaa', '**/*.bbbb']),
                bundle(fileset=['*.aaaa']),
                bundle(fileset=['**/*.abab']),
                bundle(fileset=['file1.aaaa', 'file2.aaaa']),
              ],
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
                        in pants_run.stderr_data
                    )
                else:
                    assert (
                        f"[WARN] Unmatched globs {error_origin}: [{formatted_globs}]"
                        in pants_run.stderr_data
                    )

    @unittest.skip("flaky: https://github.com/pantsbuild/pants/issues/8520")
    def test_existing_sources(self):
        target_full = f"{self._SOURCES_TARGET_BASE}:text"
        pants_run = self.run_pants(
            ["filedeps", target_full],
            config={GLOBAL_SCOPE_CONFIG_SECTION: {"files_not_found_behavior": "warn"}},
        )
        self.assert_success(pants_run)
        assert "[WARN] Unmatched glob" not in pants_run.stderr_data

    def test_missing_bundles_warnings(self):
        target_full = f"{self._BUNDLE_TARGET_BASE}:missing-bundle-fileset"
        error_origin = f"from {target_full}'s `bundles` field"
        with self.setup_bundle_target():
            pants_run = self.run_pants(
                ["filedeps", target_full],
                config={GLOBAL_SCOPE_CONFIG_SECTION: {"files_not_found_behavior": "warn"}},
            )
        self.assert_success(pants_run)
        unmatched_glob = ["*.aaaa", "**/*.abab"]
        unmatched_globs = [["**/*.aaaa", "**/*.bbbb"], ["file1.aaaa", "file2.aaaa"]]
        for glob in unmatched_glob:
            formatted_glob = f'"{os.path.join(self._BUNDLE_TARGET_BASE, glob)}"'
            assert (
                f"[WARN] Unmatched glob {error_origin}: {formatted_glob}" in pants_run.stderr_data
            )
        for globs in unmatched_globs:
            formatted_globs = ", ".join(
                f'"{os.path.join(self._BUNDLE_TARGET_BASE, glob)}"' for glob in globs
            )
            assert (
                f"[WARN] Unmatched globs {error_origin}: [{formatted_globs}]"
                in pants_run.stderr_data
            )

    @unittest.skip("flaky: https://github.com/pantsbuild/pants/issues/8520")
    def test_existing_bundles(self):
        target_full = f"{self._BUNDLE_TARGET_BASE}:mapper"
        pants_run = self.run_pants(
            ["filedeps", target_full],
            config={GLOBAL_SCOPE_CONFIG_SECTION: {"files_not_found_behavior": "warn"}},
        )
        self.assert_success(pants_run)
        self.assertNotIn("[WARN] Unmatched glob", pants_run.stderr_data)

    def test_existing_directory_with_no_build_files_fails(self):
        pants_run = self.run_pants(["list", f"{self._NO_BUILD_FILE_TARGET_BASE}::"])
        self.assert_failure(pants_run)
        self.assertIn("does not match any targets.", pants_run.stderr_data)

    @unittest.skip("flaky: https://github.com/pantsbuild/pants/issues/6787")
    def test_error_message(self):
        with self.setup_bundle_target(), self.setup_sources_targets():
            for target in self._ERR_TARGETS:
                expected_excerpts = self._ERR_TARGETS[target]
                pants_run = self.run_pants(
                    ["filedeps", target],
                    config={GLOBAL_SCOPE_CONFIG_SECTION: {"files_not_found_behavior": "error"}},
                )
                self.assert_failure(pants_run)
                for excerpt in expected_excerpts:
                    self.assertIn(excerpt, pants_run.stderr_data)
