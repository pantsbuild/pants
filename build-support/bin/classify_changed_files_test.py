# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest
from classify_changed_files import ChangeLabel, classify


@pytest.mark.parametrize(
    ["changed_files", "expected"],
    (
        [
            ["docs/path/to/some/doc", "docs/path/to/some/other/doc"],
            {ChangeLabel.docs, ChangeLabel.no_code},
        ],
        [
            ["README.md", "path/to/some/dir/README.md"],
            {ChangeLabel.docs, ChangeLabel.no_code},
        ],
        [
            ["docs/notes/2.16.x.md"],
            {ChangeLabel.docs, ChangeLabel.notes, ChangeLabel.no_code},
        ],
        [["src/rust/engine/path/to/file.rs"], {ChangeLabel.rust}],
        [["src/python/pants/VERSION"], {ChangeLabel.release}],
        [["src/python/pants_release/generate_github_workflows.py"], {ChangeLabel.ci_config}],
        [["src/python/pants/whatever.py"], {ChangeLabel.other}],
        [
            ["docs/path/to/some/doc", "src/rust/engine/rust-toolchain"],
            {ChangeLabel.docs, ChangeLabel.rust},
        ],
        [
            [
                "docs/path/to/some/doc",
                "src/rust/engine/rust-toolchain",
                "src/python/pants/whatever.py",
            ],
            {ChangeLabel.docs, ChangeLabel.rust, ChangeLabel.other},
        ],
        [
            [
                ".devcontainer/Dockerfile",
                "docs/path/to/some/doc",
            ],
            {ChangeLabel.dev_utils, ChangeLabel.docs, ChangeLabel.no_code},
        ],
    ),
)
def test_classification(changed_files, expected):
    assert classify(changed_files) == expected
