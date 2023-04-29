# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass

from pants.backend.nfpm.target_types import (
    APK_FIELDS,
    ARCHLINUX_FIELDS,
    DEB_FIELDS,
    RPM_FIELDS,
    NfpmPackageNameField,
)
from pants.core.goals.package import OutputPathField, PackageFieldSet
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class NfpmPackageFieldSet(PackageFieldSet, metaclass=ABCMeta):
    output_path: OutputPathField
    package_name: NfpmPackageNameField


@dataclass(frozen=True)
class NfpmApkPackageFieldSet(NfpmPackageFieldSet):
    required_fields = APK_FIELDS


# noinspection DuplicatedCode
@dataclass(frozen=True)
class NfpmArchlinuxPackageFieldSet(NfpmPackageFieldSet):
    required_fields = ARCHLINUX_FIELDS


# noinspection DuplicatedCode
@dataclass(frozen=True)
class NfpmDebPackageFieldSet(NfpmPackageFieldSet):
    required_fields = DEB_FIELDS


# noinspection DuplicatedCode
@dataclass(frozen=True)
class NfpmRpmPackageFieldSet(NfpmPackageFieldSet):
    required_fields = RPM_FIELDS


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, NfpmApkPackageFieldSet),
        UnionRule(PackageFieldSet, NfpmArchlinuxPackageFieldSet),
        UnionRule(PackageFieldSet, NfpmDebPackageFieldSet),
        UnionRule(PackageFieldSet, NfpmRpmPackageFieldSet),
    ]
