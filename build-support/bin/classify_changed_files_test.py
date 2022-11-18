# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest
from classify_changed_files import Affected, classify


@pytest.mark.parametrize(
    ["changed_files", "expected"],
    (
        [["docs/path/to/some/doc", "docs/path/to/some/other/doc"], {Affected.docs}],
        [["src/rust/engine/path/to/file.rs"], {Affected.rust}],
        [["src/python/pants/VERSION"], {Affected.release}],
        [["build-support/bin/generate_github_workflows.py"], {Affected.ci_config}],
        [["src/python/pants/whatever.py"], {Affected.other}],
        [["docs/path/to/some/doc", "rust-toolchain"], {Affected.docs, Affected.rust}],
        [
            ["docs/path/to/some/doc", "rust-toolchain", "src/python/pants/whatever.py"],
            {Affected.docs, Affected.rust, Affected.other},
        ],
    ),
)
def test_classification(changed_files, expected):
    assert classify(changed_files) == expected
