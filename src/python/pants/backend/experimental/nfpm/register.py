# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.nfpm import field_set
from pants.backend.nfpm import rules as nfpm_rules
from pants.backend.nfpm.target_types import (
    NfpmApkPackage,
    NfpmArchlinuxPackage,
    NfpmDebPackage,
    NfpmRpmPackage,
)


def target_types():
    return [
        NfpmApkPackage,
        NfpmArchlinuxPackage,
        NfpmDebPackage,
        NfpmRpmPackage,
    ]


def rules():
    return [
        *field_set.rules(),
        *nfpm_rules.rules(),
    ]
