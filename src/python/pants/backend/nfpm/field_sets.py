# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from pants.backend.nfpm.config import NfpmContent, NfpmFileInfo, OctalInt
from pants.backend.nfpm.fields.all import (
    NfpmOutputPathField,
    NfpmPackageMtimeField,
    NfpmPackageNameField,
)
from pants.backend.nfpm.fields.contents import (
    NfpmContentDirDstField,
    NfpmContentDstField,
    NfpmContentFileGroupField,
    NfpmContentFileModeField,
    NfpmContentFileMtimeField,
    NfpmContentFileOwnerField,
    NfpmContentFileSourceField,
    NfpmContentSrcField,
    NfpmContentSymlinkDstField,
    NfpmContentSymlinkSrcField,
    NfpmContentTypeField,
)
from pants.backend.nfpm.fields.scripts import NfpmPackageScriptsField
from pants.backend.nfpm.target_types import DEB_FIELDS
from pants.core.goals.package import PackageFieldSet
from pants.engine.fs import FileEntry
from pants.engine.rules import collect_rules
from pants.engine.target import DescriptionField, FieldSet, Target
from pants.engine.unions import UnionRule, union
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class NfpmPackageFieldSet(PackageFieldSet, metaclass=ABCMeta):
    packager: ClassVar[str]
    extension: ClassVar[str]
    output_path: NfpmOutputPathField
    package_name: NfpmPackageNameField
    mtime: NfpmPackageMtimeField
    description: DescriptionField
    scripts: NfpmPackageScriptsField

    def nfpm_config(self, tgt: Target, *, default_mtime: str | None) -> dict[str, Any]:
        config: dict[str, Any] = {
            # pants handles any globbing before passing contents to nFPM.
            "disable_globbing": True,
            "contents": [],
            "mtime": self.mtime.normalized_value(default_mtime),
        }

        def fill_nested(_nfpm_alias: str, value: Any) -> None:
            # handle nested fields (eg: deb.triggers, rpm.compression, maintainer)
            keys = _nfpm_alias.split(".")

            cfg = config
            for key in keys[:-1]:
                # NB: if key == "[]" then it is an array (.contents).
                # We can safely ignore .contents because contents fields are on
                # the nfpm content targets, not on nfpm package targets, so
                # they will not be in NfpmPackageFieldSet.required_fields.
                # "contents" gets added to the config based on the dependencies field.
                cfg.setdefault(key, {})
                cfg = cfg[key]
            if isinstance(value, FrozenDict):
                value = dict(value)
            cfg[keys[-1]] = value

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

            field_value = tgt[field].value
            # NB: This assumes that nfpm fields have 'none_is_valid_value=False'.
            if not field.required and field_value is None:
                # Omit any undefined optional values unless default applied.
                # A default ensures field_value will not be None. So, the pants interface
                # will be stable even if nFPM changes any defaults.
                continue

            fill_nested(nfpm_alias, field_value)

        for script_type, script_src in self.scripts.normalized_value.items():
            nfpm_alias = self.scripts.nfpm_aliases[script_type]
            fill_nested(nfpm_alias, script_src)

        description = self.description.value
        if description:
            config["description"] = description

        return config


# noinspection DuplicatedCode
@dataclass(frozen=True)
class NfpmDebPackageFieldSet(NfpmPackageFieldSet):
    packager = "deb"
    extension = f".{packager}"
    required_fields = DEB_FIELDS


NFPM_PACKAGE_FIELD_SET_TYPES: FrozenOrderedSet[type[NfpmPackageFieldSet]] = FrozenOrderedSet(
    (NfpmDebPackageFieldSet,)
)


@union
@dataclass(frozen=True)
class NfpmContentFieldSet(FieldSet, metaclass=ABCMeta):
    owner: NfpmContentFileOwnerField
    group: NfpmContentFileGroupField
    mode: NfpmContentFileModeField
    mtime: NfpmContentFileMtimeField

    @abstractmethod
    def nfpm_config(
        self, *, content_sandbox_files: dict[str, FileEntry], default_mtime: str | None = None
    ) -> NfpmContent:
        pass

    def file_info(
        self, default_is_executable: bool | None = None, default_mtime: str | None = None
    ) -> NfpmFileInfo:
        mode = self.mode.value
        if mode is None and default_is_executable is not None:
            # NB: The execute bit is the only mode bit we can safely get from the sandbox.
            # If we don't pass an explicit mode, nFPM will try to use the sandboxed file's mode.
            mode = 0o755 if default_is_executable else 0o644

        return NfpmFileInfo(
            owner=self.owner.value,
            group=self.group.value,
            mode=OctalInt(mode) if mode is not None else mode,
            mtime=self.mtime.normalized_value(default_mtime),
        )


@dataclass(frozen=True)
class NfpmContentDirFieldSet(NfpmContentFieldSet):
    required_fields = (NfpmContentDirDstField,)

    dst: NfpmContentDirDstField

    def nfpm_config(
        self, *, content_sandbox_files: dict[str, FileEntry], default_mtime: str | None = None
    ) -> NfpmContent:
        return NfpmContent(
            type="dir",
            dst=self.dst.value,
            file_info=self.file_info(default_mtime=default_mtime),
        )


@dataclass(frozen=True)
class NfpmContentSymlinkFieldSet(NfpmContentFieldSet):
    required_fields = (NfpmContentSymlinkDstField,)

    src: NfpmContentSymlinkSrcField
    dst: NfpmContentSymlinkDstField

    def nfpm_config(
        self, *, content_sandbox_files: dict[str, FileEntry], default_mtime: str | None = None
    ) -> NfpmContent:
        return NfpmContent(
            type="symlink",
            src=self.src.value,
            dst=self.dst.value,
            file_info=self.file_info(default_mtime=default_mtime),
        )


@dataclass(frozen=True)
class NfpmContentFileFieldSet(NfpmContentFieldSet):
    required_fields = (NfpmContentDstField,)

    source: NfpmContentFileSourceField
    src: NfpmContentSrcField
    dst: NfpmContentDstField
    content_type: NfpmContentTypeField

    class InvalidTarget(Exception):
        pass

    class SrcMissingFomSandbox(Exception):
        pass

    def nfpm_config(
        self, *, content_sandbox_files: dict[str, FileEntry], default_mtime: str | None = None
    ) -> NfpmContent:
        source: str | None = self.source.file_path
        src: str | None = self.src.file_path
        dst: str = self.dst.value
        if source is not None and not src:
            # If defined, 'source' provides the default value for 'src'.
            src = source
        if src is None:  # src is NOT required; prepare to raise an error.
            raise self.InvalidTarget()
        sandbox_file: FileEntry | None = content_sandbox_files.get(src)
        if sandbox_file is None:
            raise self.SrcMissingFomSandbox()
        return NfpmContent(
            type=self.content_type.value,
            src=src,
            dst=dst,
            file_info=self.file_info(sandbox_file.is_executable, default_mtime),
        )


NFPM_CONTENT_FIELD_SET_TYPES: FrozenOrderedSet[type[NfpmContentFieldSet]] = FrozenOrderedSet(
    (
        NfpmContentDirFieldSet,
        NfpmContentSymlinkFieldSet,
        NfpmContentFileFieldSet,
    )
)


def rules():
    return [
        *collect_rules(),
        *(
            UnionRule(PackageFieldSet, field_set_type)
            for field_set_type in NFPM_PACKAGE_FIELD_SET_TYPES
        ),
        *(
            UnionRule(NfpmContentFieldSet, field_set_type)
            for field_set_type in NFPM_CONTENT_FIELD_SET_TYPES
        ),
    ]
