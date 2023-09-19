# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import enum
import fnmatch
import sys
from collections import defaultdict

# This script may be run in CI before Pants is bootstrapped, so it must be kept simple
# and runnable without `./pants run`.


class Affected(enum.Enum):
    docs = "docs"
    rust = "rust"
    release = "release"
    ci_config = "ci_config"
    other = "other"


_docs_globs = [
    "*.md",
    "**/*.md",
    "docs/*",
    "build-support/bin/generate_user_list.py",
]
_rust_globs = [
    "src/rust/engine/*",
    "build-support/bin/rust/*",
]
_release_globs = [
    # Any changes to these files should trigger wheel building. Notes too, as they are included in
    # the wheel.
    "pants.toml",
    "src/python/pants/VERSION",
    "src/python/pants/init/BUILD",
    "src/python/pants/notes/*",
    "src/python/pants_release/release.py",
    "src/python/pants_release/reversion.py",
]
_ci_config_globs = [
    "build-support/bin/classify_changed_files.py",
    "src/python/pants_release/generate_github_workflows.py",
]


_affected_to_globs = {
    Affected.docs: _docs_globs,
    Affected.rust: _rust_globs,
    Affected.release: _release_globs,
    Affected.ci_config: _ci_config_globs,
}


def classify(changed_files: list[str]) -> set[Affected]:
    classified: dict[Affected, set[str]] = defaultdict(set)
    for affected, globs in _affected_to_globs.items():
        for pattern in globs:
            classified[affected].update(fnmatch.filter(changed_files, pattern))
    ret = {k for k, v in classified.items() if v}
    if set(changed_files) - set().union(*classified.values()):
        ret.add(Affected.other)
    return ret


def main() -> None:
    affecteds = classify(sys.stdin.read().splitlines())
    for affected in sorted([a.name for a in affecteds]):
        print(affected)


if __name__ == "__main__":
    main()
