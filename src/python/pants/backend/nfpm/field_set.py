# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass
from typing import Any, ClassVar, cast

from typing_extensions import Protocol

from pants.backend.nfpm.fields.all import NfpmPackageNameField
from pants.backend.nfpm.target_types import APK_FIELDS, ARCHLINUX_FIELDS, DEB_FIELDS, RPM_FIELDS
from pants.core.goals.package import OutputPathField, PackageFieldSet
from pants.engine.rules import collect_rules
from pants.engine.target import DescriptionField, Target
from pants.engine.unions import UnionRule


# This allows us to define the nFPM config option name on the field
class _NfpmField(Protocol):
    # nfpm_alias is a "." concatenated series of dict keys (keys of nfpm.yaml).
    nfpm_alias: ClassVar[str]


@dataclass(frozen=True)
class NfpmPackageFieldSet(PackageFieldSet, metaclass=ABCMeta):
    output_path: OutputPathField
    package_name: NfpmPackageNameField
    description: DescriptionField

    def nfpm_config(self, tgt: Target) -> dict[str, Any]:
        config: dict[str, Any] = {}
        for field in self.required_fields:
            value = tgt[field].value
            if not field.required and value is None:
                # omit undefined optional values from nfpm.yaml
                continue

            # handle nested fields (eg: deb.triggers)
            keys = cast(_NfpmField, field).nfpm_alias.split(".")

            cfg = config
            for key in keys[:-1]:
                # TODO: if key == "[]" then it is an array (.contents)
                cfg.setdefault(key, {})
                cfg = cfg[key]
            cfg[keys[-1]] = value

        description = self.description.value
        if description:
            config["description"] = description

        return config


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
