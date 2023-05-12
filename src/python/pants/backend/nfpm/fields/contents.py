# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import ClassVar, Sequence

from pants.engine.target import SequenceField, StringField, StringSequenceField, IntField, ScalarField
from pants.util.strutil import help_text


class NfpmContentSrcField(StringField):
    nfpm_alias = "contents.[].src"
    alias: ClassVar[str] = "src"
    help = help_text(
        lambda: f"""
        """
    )


class NfpmContentDestField(StringField):
    nfpm_alias = "contents.[].dest"
    alias: ClassVar[str] = "dest"
    help = help_text(
        lambda: f"""
        """
    )


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
        """
    )


class NfpmContentSymlinkDestField(NfpmContentDestField):
    help = help_text(
        lambda: f"""
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


class NfpmContentDirDestField(NfpmContentDestField):
    help = help_text(
        lambda: f"""
        """
    )


class NfpmContentDirsField(StringSequenceField):
    nfpm_alias = ""
    alias: ClassVar[str] = "dirs"
    help = help_text(
        lambda: f"""
        """
    )
