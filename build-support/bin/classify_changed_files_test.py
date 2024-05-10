# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest
from classify_changed_files import Affected, classify


@pytest.mark.parametrize(
    ["changed_files", "expected"],
    (
        [["docs/path/to/some/doc", "docs/path/to/some/other/doc"], {Affected.docs}],
        [
            ["README.md", "path/to/some/dir/README.md"],
            {Affected.docs},
        ],
        [
            ["docs/notes/2.16.x.md"],
            {Affected.docs, Affected.notes},
        ],
        [["src/rust/engine/path/to/file.rs"], {Affected.rust}],
        [["src/python/pants/VERSION"], {Affected.release}],
        [["src/python/pants_release/generate_github_workflows.py"], {Affected.ci_config}],
        [["src/python/pants/whatever.py"], {Affected.other}],
        [
            ["docs/path/to/some/doc", "src/rust/engine/rust-toolchain"],
            {Affected.docs, Affected.rust},
        ],
        [
            [
                "docs/path/to/some/doc",
                "src/rust/engine/rust-toolchain",
                "src/python/pants/whatever.py",
            ],
            {Affected.docs, Affected.rust, Affected.other},
        ],
    ),
)
def test_classification(changed_files, expected):
    assert classify(changed_files) == expected
