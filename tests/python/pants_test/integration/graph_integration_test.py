# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from typing import Iterator

from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.testutil.pants_integration_test import run_pants
from pants.util.contextutil import overwrite_file_content

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
def setup_sources_targets() -> Iterator[None]:
    build_path = Path(_SOURCES_TARGET_BASE, "BUILD")
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
    with overwrite_file_content(build_path, f"{original_content}\n{new_content}"):
        yield


# See https://github.com/pantsbuild/pants/issues/8520 for past flakiness of this test.
def test_missing_sources_warnings():
    target_to_unmatched_globs = {
        "missing-globs": ["*.a"],
        "missing-rglobs": ["**/*.a"],
        "missing-literal-files": ["another_nonexistent_file.txt", "nonexistent_test_file.txt"],
    }
    with setup_sources_targets():
        for target in target_to_unmatched_globs:
            target_full = f"{_SOURCES_TARGET_BASE}:{target}"
            pants_run = run_pants(
                ["filedeps", target_full],
                config={GLOBAL_SCOPE_CONFIG_SECTION: {"unmatched_build_file_globs": "warn"}},
            )
            pants_run.assert_success()
            unmatched_globs = target_to_unmatched_globs[target]
            formatted_globs = ", ".join(
                f'"{os.path.join(_SOURCES_TARGET_BASE, glob)}"' for glob in unmatched_globs
            )
            error_origin = f"from {_SOURCES_TARGET_BASE}:{target}'s `sources` field"
            if len(unmatched_globs) == 1:
                assert (
                    f"[WARN] Unmatched glob {error_origin}: {formatted_globs}" in pants_run.stderr
                )
            else:
                assert (
                    f"[WARN] Unmatched globs {error_origin}: [{formatted_globs}]"
                    in pants_run.stderr
                )


# See https://github.com/pantsbuild/pants/issues/8520 for past flakiness of this test.
def test_existing_sources():
    target_full = f"{_SOURCES_TARGET_BASE}:text"
    pants_run = run_pants(
        ["filedeps", target_full],
        config={GLOBAL_SCOPE_CONFIG_SECTION: {"unmatched_build_file_globs": "warn"}},
    )
    pants_run.assert_success()
    assert "[WARN] Unmatched glob" not in pants_run.stderr


# See https://github.com/pantsbuild/pants/issues/6787 for past flakiness of this test.
def test_error_message():
    with setup_sources_targets():
        for target in _ERR_TARGETS:
            expected_excerpts = _ERR_TARGETS[target]
            pants_run = run_pants(
                ["filedeps", target],
                config={GLOBAL_SCOPE_CONFIG_SECTION: {"unmatched_build_file_globs": "error"}},
            )
            pants_run.assert_failure()
            for excerpt in expected_excerpts:
                assert excerpt in pants_run.stderr
