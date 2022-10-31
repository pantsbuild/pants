# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.build_files.fix.deprecations import renamed_fields_rules, renamed_targets_rules


def rules():
    return [
        *renamed_targets_rules.rules(),
        *renamed_fields_rules.rules(),
    ]
