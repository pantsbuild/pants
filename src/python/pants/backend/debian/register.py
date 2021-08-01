# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.debian import rules as debian_rules
from pants.backend.debian.target_types import DebianPackage


def target_types():
    return [DebianPackage]


def rules():
    return [*debian_rules.rules()]
