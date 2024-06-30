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
    "testprojects/src/python/sources:missing-sources": 'Unmatched glob from testprojects/src/python/sources:missing-sources\'s `sources` field: "testprojects/src/python/sources/*.scala", excludes: ["testprojects/src/python/sources/*Spec.scala", "testprojects/src/python/sources/*Suite.scala", "testprojects/src/python/sources/*Test.scala"]',
}


@contextmanager
def setup_sources_targets() -> Iterator[None]:
    build_path = Path(_SOURCES_TARGET_BASE, "BUILD")
    original_content = build_path.read_text()
    new_content = dedent(
        """\
        scala_sources(
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


def _config(warn_on_unmatched_globs: bool) -> dict:
    return {
        GLOBAL_SCOPE_CONFIG_SECTION: {
            "backend_packages": ["pants.backend.python", "pants.backend.experimental.scala"],
            "unmatched_build_file_globs": "warn" if warn_on_unmatched_globs else "error",
        }
    }


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
                config=_config(warn_on_unmatched_globs=True),
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
        config=_config(warn_on_unmatched_globs=True),
    )
    pants_run.assert_success()
    assert "[WARN] Unmatched glob" not in pants_run.stderr


# See https://github.com/pantsbuild/pants/issues/6787 for past flakiness of this test.
def test_error_message():
    with setup_sources_targets():
        for target in _ERR_TARGETS:
            expected_excerpt = _ERR_TARGETS[target]
            pants_run = run_pants(
                ["filedeps", target],
                config=_config(warn_on_unmatched_globs=False),
            )
            pants_run.assert_failure()
            assert expected_excerpt in pants_run.stderr
