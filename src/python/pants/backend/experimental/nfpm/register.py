# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.nfpm.rules import rules as nfpm_rules
from pants.backend.nfpm.subsystem import rules as nfpm_subsystem_rules
from pants.backend.nfpm.target_types import target_types as nfpm_target_types
from pants.backend.nfpm.target_types_rules import rules as nfpm_target_type_rules


def target_types():
    return nfpm_target_types()


def rules():
    return [
        *nfpm_subsystem_rules(),
        *nfpm_target_type_rules(),
        *nfpm_rules(),
    ]
