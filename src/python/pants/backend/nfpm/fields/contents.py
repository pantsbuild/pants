# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import ClassVar, Sequence

from pants.backend.nfpm.fields.all import NfpmDependencies
from pants.core.target_types import FileTarget, RelocatedFiles
from pants.engine.target import SequenceField, StringField, StringSequenceField, IntField, ScalarField, OptionalSingleSourceField
from pants.util.strutil import help_text


# -----------------------------------------------------------------------------------------------
# file_info fields
# -----------------------------------------------------------------------------------------------


class NfpmContentFileOwnerField(StringField):
    nfpm_alias = "contents.[].file_info.owner"
    alias: ClassVar[str] = "file_owner"
    default = "root"  # Make the nFPM default visible in help.
    help = help_text(
        lambda: f"""
        Username that owns this file or directory.

        This is like the OWNER arg in chown: https://www.mankier.com/1/chown
        """
    )


class NfpmContentFileGroupField(StringField):
    nfpm_alias = "contents.[].file_info.group"
    alias: ClassVar[str] = "file_group"
    default = "root"  # Make the nFPM default visible in help.
    help = help_text(
        lambda: f"""
        Name of the group that owns this file or directory.

        This is like the GROUP arg in chown: https://www.mankier.com/1/chown
        """
    )


class NfpmContentFileModeField(IntField):
    # TODO: validate that this is an octal, not just an int.
    # TODO: allow putting this as a string in BUILD files.
    nfpm_alias = "contents.[].file_info.mode"
    alias: ClassVar[str] = "file_mode"
    # TODO: pants does not materialize mode (except the executable bit) in the sandbox
    # TODO: use the digest's execute bit to default to either 0o644 or 0o755
    #       and bypass any nFPM auto detection confusion.
    help = help_text(
        lambda: f"""
        The file mode bits in octal format (starts with 0 or 0o).

        If not defined, nFPM pulls the mode from the sandboxed source file.
        However, pants only propagates the executable file mode bit into the
        sandbox, so no other mode bits can be automatically pulled.
        So this can be lossy if not defined.

        This is like the OCTAL-MODE arg in chmod: https://www.mankier.com/1/chmod
        """
    )


class NfpmContentFileMtimeField(StringField):
    nfpm_alias = "contents.[].file_info.mtime"
    alias: ClassVar[str] = "file_mtime"
    # Default copied from PEX (which uses zipfile standard MS-DOS epoch).
    # https://github.com/pantsbuild/pex/blob/v2.1.137/pex/common.py#L39-L45
    default = "1980-01-01T00:00:00"
    # TODO: override default with SOURCE_DATE_EPOCH env var if defined
    # TODO: there are many things in nFPM that use time.Now(), so upstream nFPM work
    #       is required so pants can use SOURCE_DATE_EPOCH to overwrite that.
    help = help_text(
        lambda: f"""
        The file modification time as an RFC 3339 formatted string.

        For example: 2008-01-02T15:04:05Z

        The format is defined in RFC 3339: https://rfc-editor.org/rfc/rfc3339.html

        Though nFPM supports pulling mtime from the src file or directory in most
        cases, the pants nfpm backend does not support this. Reading the mtime from
        the filesystem is problematic because Pants does not track the mtime of files
        and does not propagate any file mtime into the sandboxes. Reasons for this
        include: git does not track mtime, timestamps like mtime cause many issues
        for reproducible packaging builds, and reproducible builds are required
        for pants to provide its fine-grained caches.

        See also: https://reproducible-builds.org/docs/timestamps/
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
        The nFPM content type for the packaged file.

        The content type can be either a standard file ({repr(NfpmContentFileType.file.value)}),
        the default, or a config file ({repr(NfpmContentFileType.config.value)}).

        For RPM packaged files, the content type can also be one of
        {repr(NfpmContentFileType.config_noreplace.value)}, {repr(NfpmContentFileType.doc.value)},
        {repr(NfpmContentFileType.license.value)}, and {repr(NfpmContentFileType.readme.value)}.
        The {repr(NfpmContentFileType.config_noreplace.value)} type is used for RPM's
        `%config(noreplace)` option. For packagers other than RPM, using
        {repr(NfpmContentFileType.config_noreplace.value)} is the same as
        {repr(NfpmContentFileType.config.value)}. The other RPM-specific types are equivalent to
        {repr(NfpmContentFileType.file.value)} if used with other packagers.

        This field only supports file-specific nFPM content types. Please use these targets for non-file content:

        - For 'dir' content, use the `nfpm_content_dir` and `nfpm_content_dirs` targets.
        - For 'symlink' content, use the `nfpm_content_symlink` and `nfpm_content_symlinks` targets.
        - For 'ghost' content, which is only for RPM, use the 'ghost_contents' field on the `nfpm_rpm_package` target.

        Pants expands globs before passing the list of contents to nFPM. So, pants does
        not support nFPM's 'tree' content type.
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
