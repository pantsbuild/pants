# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass
from typing import Any, ClassVar

from pants.backend.nfpm.fields.all import NfpmOutputPathField, NfpmPackageNameField
from pants.backend.nfpm.fields.rpm import NfpmRpmGhostContents
from pants.backend.nfpm.target_types import APK_FIELDS, ARCHLINUX_FIELDS, DEB_FIELDS, RPM_FIELDS
from pants.core.goals.package import PackageFieldSet
from pants.engine.rules import collect_rules
from pants.engine.target import DescriptionField, Target
from pants.engine.unions import UnionRule
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class NfpmPackageFieldSet(PackageFieldSet, metaclass=ABCMeta):
    packager: ClassVar[str]
    output_path: NfpmOutputPathField
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
                # NB: if key == "[]" then it is an array (.contents).
                # We can safely ignore .contents because contents fields are on
                # the nfpm content targets, not on nfpm package targets, so
                # they will not be in NfpmPackageFieldSet.required_fields.
                # "contents" gets added to the config based on the dependencies field.
                cfg.setdefault(key, {})
                cfg = cfg[key]
            cfg[keys[-1]] = value

        description = self.description.value
        if description:
            config["description"] = description

        return config


@dataclass(frozen=True)
class NfpmApkPackageFieldSet(NfpmPackageFieldSet):
    packager = "apk"
    required_fields = APK_FIELDS


# noinspection DuplicatedCode
@dataclass(frozen=True)
class NfpmArchlinuxPackageFieldSet(NfpmPackageFieldSet):
    packager = "archlinux"
    # NB: uses *.tar.zst (unlike the other packagers where packager == file extension)
    required_fields = ARCHLINUX_FIELDS


# noinspection DuplicatedCode
@dataclass(frozen=True)
class NfpmDebPackageFieldSet(NfpmPackageFieldSet):
    packager = "deb"
    required_fields = DEB_FIELDS


# noinspection DuplicatedCode
@dataclass(frozen=True)
class NfpmRpmPackageFieldSet(NfpmPackageFieldSet):
    packager = "rpm"
    required_fields = RPM_FIELDS
    ghost_contents = NfpmRpmGhostContents

    def nfpm_config(self, tgt: Target) -> dict[str, Any]:
        config = super().nfpm_config(tgt)
        config["contents"].extend(self.ghost_contents.nfpm_contents)
        return config


NFPM_PACKAGE_FIELD_SET_TYPES = FrozenOrderedSet(
    (
        NfpmApkPackageFieldSet,
        NfpmArchlinuxPackageFieldSet,
        NfpmDebPackageFieldSet,
        NfpmRpmPackageFieldSet,
    )
)


def rules():
    return [
        *collect_rules(),
        *(
            UnionRule(PackageFieldSet, field_set_type)
            for field_set_type in NFPM_PACKAGE_FIELD_SET_TYPES
        ),
    ]
