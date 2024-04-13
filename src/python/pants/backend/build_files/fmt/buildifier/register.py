# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.build_files.fmt.buildifier import rules as buildifier_rules


def rules():
    return [
        *buildifier_rules.rules(),
    ]
