# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.check.pip_audit import rules as pip_audit_rules
from pants.backend.python.check.pip_audit import skip_field, subsystem


def rules():
    return (*pip_audit_rules.rules(), *skip_field.rules(), *subsystem.rules())
