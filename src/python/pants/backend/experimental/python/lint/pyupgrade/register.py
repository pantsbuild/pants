# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import logging

from pants.backend.python.lint.pyupgrade import rules as pyupgrade_rules

logger = logging.getLogger(__name__)


def rules():
    logger.warning(
        "DEPRECATED: The pyupgrade plugin has moved to `pants.backend.python.lint.pyupgrade`"
        + " (and is a part of the `fix` goal)."
    )
    return pyupgrade_rules()
