# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.tools.workunit_logger import rules as workunit_logger_rules


def rules():
    return [
        *workunit_logger_rules.rules(),
    ]
