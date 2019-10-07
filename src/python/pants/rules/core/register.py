# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.rules.core import filedeps, fmt, list_roots, list_targets, strip_source_root, test


def rules():
    return [
        *fmt.rules(),
        *list_roots.rules(),
        *list_targets.rules(),
        *filedeps.rules(),
        *strip_source_root.rules(),
        *test.rules(),
    ]
