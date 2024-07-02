# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.nfpm.rules import rules as nfpm_rules
from pants.backend.nfpm.target_types import (
    NfpmApkPackage,
    NfpmArchlinuxPackage,
    NfpmContentDir,
    NfpmContentDirs,
    NfpmContentFile,
    NfpmContentFiles,
    NfpmContentSymlink,
    NfpmContentSymlinks,
    NfpmDebPackage,
    NfpmRpmPackage,
)
from pants.backend.nfpm.target_types_rules import rules as target_type_rules


def target_types():
    return [
        NfpmApkPackage,
        NfpmArchlinuxPackage,
        NfpmDebPackage,
        NfpmRpmPackage,
        NfpmContentFile,
        NfpmContentFiles,
        NfpmContentSymlink,
        NfpmContentSymlinks,
        NfpmContentDir,
        NfpmContentDirs,
    ]


def rules():
    return [
        *target_type_rules(),
        *nfpm_rules(),
    ]
