# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.backend.python.lint.autoflake.register import rules as autoflake_rules

logger = logging.getLogger(__name__)


def rules():
    logger.warning(
        "DEPRECATED: The autoflake plugin has moved to `pants.backend.python.lint.autoflake`"
        + " (and from the `fmt` goal to the `fix` goal)."
    )
    return autoflake_rules()
