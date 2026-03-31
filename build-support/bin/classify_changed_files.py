# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import enum
import fnmatch
import sys
from collections import defaultdict

# This script may be run in CI before Pants is bootstrapped, so it must be kept simple
# and runnable without `./pants run`.


class ChangeLabel(enum.Enum):
    dev_utils = "dev_utils"
    docs = "docs"
    rust = "rust"
    release = "release"
    ci_config = "ci_config"
    notes = "notes"
    other = "other"
    no_code = "no_code"


_dev_utils_globs = [
    ".devcontainer/*",
]

_docs_globs = [
    "*.md",
    "**/*.md",
    "docs/*",
]
_rust_globs = [
    "src/rust/*",
    "build-support/bin/rust/*",
]
_release_globs = [
    # Any changes to these files should trigger wheel building.
    "pants.toml",
    "src/python/pants/VERSION",
    "src/python/pants/init/BUILD",
    "src/python/pants_release/release.py",
]
_ci_config_globs = [
    "build-support/bin/classify_changed_files.py",
    "src/python/pants_release/generate_github_workflows.py",
]
_notes_globs = [
    "docs/notes/*",
]


_affected_to_globs = {
    ChangeLabel.dev_utils: _dev_utils_globs,
    ChangeLabel.docs: _docs_globs,
    ChangeLabel.rust: _rust_globs,
    ChangeLabel.release: _release_globs,
    ChangeLabel.ci_config: _ci_config_globs,
    ChangeLabel.notes: _notes_globs,
}


def classify(changed_files: list[str]) -> set[ChangeLabel]:
    classified: dict[ChangeLabel, set[str]] = defaultdict(set)
    for affected, globs in _affected_to_globs.items():
        for pattern in globs:
            classified[affected].update(fnmatch.filter(changed_files, pattern))
    ret = {k for k, v in classified.items() if v}
    if set(changed_files) - set().union(*classified.values()):
        ret.add(ChangeLabel.other)
    if len(ret - {ChangeLabel.dev_utils, ChangeLabel.docs, ChangeLabel.notes}) == 0:
        ret.add(ChangeLabel.no_code)
    return ret


def main() -> None:
    affecteds = classify(sys.stdin.read().splitlines())
    print(" ".join(sorted(a.name for a in affecteds)))


if __name__ == "__main__":
    main()
