# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import ClassVar, Sequence

from pants.backend.nfpm.fields.all import NfpmDependencies
from pants.core.target_types import FileTarget, RelocatedFiles
from pants.engine.target import SequenceField, StringField, StringSequenceField, IntField, ScalarField, OptionalSingleSourceField
from pants.util.strutil import help_text


class NfpmContentFileOwnerField(StringField):
    nfpm_alias = "contents.[].file_info.owner"
    alias: ClassVar[str] = "file_owner"
    help = help_text(
        lambda: f"""
        """
    )


class NfpmContentFileGroupField(StringField):
    nfpm_alias = "contents.[].file_info.group"
    alias: ClassVar[str] = "file_group"
    help = help_text(
        lambda: f"""
        """
    )


class NfpmContentFileModeField(IntField):
    nfpm_alias = "contents.[].file_info.mode"
    alias: ClassVar[str] = "file_mode"
    help = help_text(
        lambda: f"""
        """
    )


class NfpmContentFileMtimeField(StringField):
    nfpm_alias = "contents.[].file_info.mtime"
    alias: ClassVar[str] = "file_mtime"
    help = help_text(
        lambda: f"""
        """
    )


# -----------------------------------------------------------------------------------------------
# File-specific fields
# -----------------------------------------------------------------------------------------------

class NfpmContentFileSourceField(OptionalSingleSourceField):
    nfpm_alias = ""
    none_is_valid_value = True
    # Maybe set this similar to DockerImageSourceField...
    # default_glob_match_error_behavior =
    help = help_text(
        lambda: f"""
        A file that should be copied into an nfpm package (optional).

        Either specify a file with '{NfpmContentFileSourceField.alias}', or use
        '{NfpmDependencies.alias}' to add a dependency on the target that owns
        the file.

        If both '{NfpmContentSrcField.alias}' and '{NfpmContentFileSourceField.alias}'
        are populated, then the file in '{NfpmContentFileSourceField.alias}' will be
        placed in the sandbox at the '{NfpmContentSrcField.alias}' path (similar to
        how the '{RelocatedFiles.alias}' target works).
        """
    )


class NfpmContentSrcField(StringField):
    nfpm_alias = "contents.[].src"
    alias: ClassVar[str] = "src"
    help = help_text(
        lambda: f"""
        A file path that should be included in the package.

        When the package gets installed, the file from '{NfpmContentSrcField.alias}'
        will be installed using the absolute path in '{NfpmContentDstField.alias}'.

        This path should be relative to the sandbox. The path should point to a
        generated file or a real file sourced from the workspace.

        The '{NfpmContentSrcField.alias}' defaults to the file referenced in the
        '{NfpmContentFileSourceField.alias}' field, if provided. Otherwise, this
        defaults to the path of the first '{FileTarget.alias}' target listed in the
        '{NfpmDependencies.alias}'.

        If both '{NfpmContentSrcField.alias}' and '{NfpmContentFileSourceField.alias}'
        are populated, then the file in '{NfpmContentFileSourceField.alias}' will be
        placed in the sandbox at the '{NfpmContentSrcField.alias}' path (similar to
        how the '{RelocatedFiles.alias}' target works).
        """
    )


class NfpmContentDstField(StringField):
    nfpm_alias = "contents.[].dst"
    alias: ClassVar[str] = "dst"
    help = help_text(
        lambda: f"""
        The absolute install path for a packaged file.

        When the package gets installed, the file from '{NfpmContentSrcField.alias}'
        will be installed using the absolute path in '{NfpmContentDstField.alias}'.

        This path is an absolute path on the file system where the package
        will be installed.
        """
    )


class NfpmContentFileType(Enum):
    # This is a subset of the nFPM content types that apply to individual files.
    # Do not include these:
    # - dir (not a file: handled by nfpm_content_dir target)
    # - tree (not a file: pants needs more explicit config to build sandbox)
    # - ghost (handled by ghost_contents field on nfpm_rpm_package target)
    # - symlink (handled by a nfpm_content_symlink target)
    file = ""
    config = "config"
    # config|noreplace is only used by rpm.
    # For other packagers (deb, apk, archlinux) this is the same as "config".
    config_noreplace = "config|noreplace"
    # These are undocumented, but present in nFPM code for rpm.
    # If used, this changes the type used in the rpm header.
    # For other packagers (deb, apk, archlinux) this is the same as "file".
    doc = "doc"
    license = "license"  # nFPM also supports "licence"
    readme = "readme"


class NfpmContentTypeField(StringField):
    nfpm_alias = "contents.[].type"
    alias: ClassVar[str] = "content_type"
    valid_choices = NfpmContentFileType
    default = NfpmContentFileType.file.value
    help = help_text(
        lambda: f"""
        """
    )


class NfpmContentFilesField(SequenceField[Sequence[str, str]]):
    nfpm_alias = ""
    alias: ClassVar[str] = "files"
    help = help_text(
        lambda: f"""
        """
    )


# -----------------------------------------------------------------------------------------------
# Symlink-specific fields
# -----------------------------------------------------------------------------------------------


class NfpmContentSymlinkSrcField(NfpmContentSrcField):
    help = help_text(
        lambda: f"""
        The symlink target path (on package install).

        When the package gets installed, a symlink will be installed at the
        '{NfpmContentDstField.alias}' path. The symlink will point to the
        '{NfpmContentSymlinkSrcField.alias}' path (the symlink target).

        This path is a path on the file system where the package will be installed.
        If this path is absolute, it is the absolute path to the symlink's target path.
        If this path is relative, it is relative to the '{NfpmContentSymlinkDstField.alias}'
        path, which is where the symlink will be created.
        """
    )


class NfpmContentSymlinkDstField(NfpmContentDstField):
    help = help_text(
        lambda: f"""
        The symlink path (on package install).

        When the package gets installed, a symlink will be installed at the
        '{NfpmContentDstField.alias}' path. The symlink will point to the
        '{NfpmContentSymlinkSrcField.alias}' path (the symlink target).

        This path is an absolute path on the file system where the package
        will be installed.
        """
    )


class NfpmContentSymlinksField(SequenceField[Sequence[str, str]]):
    nfpm_alias = ""
    alias: ClassVar[str] = "symlinks"
    help = help_text(
        lambda: f"""
        """
    )


# -----------------------------------------------------------------------------------------------
# Dir-specific fields
# -----------------------------------------------------------------------------------------------


class NfpmContentDirDstField(NfpmContentDstField):
    help = help_text(
        lambda: f"""
        The absolute install path for a directory.

        When the package gets installed, a directory will be created at the
        '{NfpmContentDirDstField.alias}' path.

        This path is an absolute path on the file system where the package
        will be installed.
        """
    )


class NfpmContentDirsField(StringSequenceField):
    nfpm_alias = ""
    alias: ClassVar[str] = "dirs"
    help = help_text(
        lambda: f"""
        """
    )
