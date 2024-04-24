# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging

from pants.backend.audit.audit import rules as audit_rules
from pants.backend.audit.pip_audit_rule import rules as pip_audit_rules

logger = logging.getLogger(__name__)


def rules():
    return (
        *audit_rules(),
        *pip_audit_rules(),
    )
