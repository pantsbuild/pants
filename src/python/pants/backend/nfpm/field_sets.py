# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass
from typing import Any

from pants.backend.nfpm.fields.all import NfpmPackageNameField
from pants.backend.nfpm.fields.rpm import NfpmRpmGhostContents
from pants.backend.nfpm.target_types import APK_FIELDS, ARCHLINUX_FIELDS, DEB_FIELDS, RPM_FIELDS
from pants.core.goals.package import OutputPathField, PackageFieldSet
from pants.engine.rules import collect_rules
from pants.engine.target import DescriptionField, Target
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class NfpmPackageFieldSet(PackageFieldSet, metaclass=ABCMeta):
    output_path: OutputPathField
    package_name: NfpmPackageNameField
    description: DescriptionField

    def nfpm_config(self, tgt: Target) -> dict[str, Any]:
        config: dict[str, Any] = {
            # pants handles any globbing before passing contents to nFPM.
            "disable_globbing": True,
            "contents": [],
        }
        for field in self.required_fields:
            # NB: This assumes that nfpm fields have a str 'nfpm_alias' attribute.
            if not hasattr(field, "nfpm_alias"):
                # Ignore field that is not defined in the nfpm backend.
                continue
            # nfpm_alias is a "." concatenated series of nfpm.yaml dict keys.
            nfpm_alias: str = getattr(field, "nfpm_alias", "")
            if not nfpm_alias:
                # field opted out of being included in this config (like dependencies)
                continue

            value = tgt[field].value
            # NB: This assumes that nfpm fields have 'none_is_valid_value=False'.
            if not field.required and value is None:
                # Omit any undefined optional values unless default applied.
                # A default ensures value will not be None. So, the pants interface
                # will be stable even if nFPM changes any defaults.
                continue

            # handle nested fields (eg: deb.triggers, rpm.compression, maintainer)
            keys = nfpm_alias.split(".")

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
    ghost_contents = NfpmRpmGhostContents

    def nfpm_config(self, tgt: Target) -> dict[str, Any]:
        config = super().nfpm_config(tgt)
        config["contents"].extend(self.ghost_contents.nfpm_contents)
        return config


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, NfpmApkPackageFieldSet),
        UnionRule(PackageFieldSet, NfpmArchlinuxPackageFieldSet),
        UnionRule(PackageFieldSet, NfpmDebPackageFieldSet),
        UnionRule(PackageFieldSet, NfpmRpmPackageFieldSet),
    ]
