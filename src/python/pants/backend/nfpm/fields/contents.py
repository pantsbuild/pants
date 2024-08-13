# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import stat
from enum import Enum
from typing import Any, ClassVar, Iterable, Optional, Union, cast

from pants.backend.nfpm.fields.all import NfpmDependencies
from pants.backend.nfpm.subsystem import mtime_default
from pants.core.target_types import RelocatedFiles
from pants.engine.addresses import Address
from pants.engine.target import (
    AsyncFieldMixin,
    Field,
    ImmutableValue,
    IntField,
    InvalidFieldException,
    InvalidFieldTypeException,
    OptionalSingleSourceField,
    OverridesField,
    StringField,
    StringSequenceField,
    ValidNumbers,
)
from pants.util.frozendict import FrozenDict
from pants.util.strutil import help_text, softwrap

# -----------------------------------------------------------------------------------------------
# file_info fields
# -----------------------------------------------------------------------------------------------


class NfpmContentFileOwnerField(StringField):
    nfpm_alias = "contents.[].file_info.owner"
    alias: ClassVar[str] = "file_owner"
    default = "root"  # Make the nFPM default visible in help.
    help = help_text(
        """
        Username that should own this packaged file or directory.

        This is like the OWNER arg in chown: https://www.mankier.com/1/chown
        """
    )


class NfpmContentFileGroupField(StringField):
    nfpm_alias = "contents.[].file_info.group"
    alias: ClassVar[str] = "file_group"
    default = "root"  # Make the nFPM default visible in help.
    help = help_text(
        """
        Name of the group that should own this packaged file or directory.

        This is like the GROUP arg in chown: https://www.mankier.com/1/chown
        """
    )


# inlined private var from https://github.com/python/cpython/blob/3.9/Lib/stat.py#L128-L154
_FILEMODE_TABLE = (
    (),  # exclude irrelevant filetype bits that are in stat._filemode_table
    ((stat.S_IRUSR, "r"),),
    ((stat.S_IWUSR, "w"),),
    ((stat.S_IXUSR | stat.S_ISUID, "s"), (stat.S_ISUID, "S"), (stat.S_IXUSR, "x")),
    ((stat.S_IRGRP, "r"),),
    ((stat.S_IWGRP, "w"),),
    ((stat.S_IXGRP | stat.S_ISGID, "s"), (stat.S_ISGID, "S"), (stat.S_IXGRP, "x")),
    ((stat.S_IROTH, "r"),),
    ((stat.S_IWOTH, "w"),),
    ((stat.S_IXOTH | stat.S_ISVTX, "t"), (stat.S_ISVTX, "T"), (stat.S_IXOTH, "x")),
)
_FILEMODE_CHARS = set("-rwxsStT")


def _parse_filemode(filemode: str) -> int:
    """Parse string filemode into octal representation.

    This is the opposite of stat.filemode, except that it does not support the filetype bits.
    """
    if len(filemode) != 9:
        raise ValueError(f"Symbolic file mode must be exactly 9 characters, not {len(filemode)}.")
    if not _FILEMODE_CHARS.issuperset(filemode):
        raise ValueError(
            "Cannot parse symbolic file mode with unknown symbols: "
            + "".join(set(filemode).difference(_FILEMODE_CHARS))
        )

    mode = 0
    # enumerate starting with index 1 to avoid irrelevant filetype bits.
    for i, symbol in enumerate(filemode, 1):
        if symbol == "-":
            continue
        for bit, char in _FILEMODE_TABLE[i]:
            if symbol == char:
                mode = mode | bit
                break
        else:
            # else none of the chars matched symbol (loop didn't hit break)
            raise ValueError(
                f"Symbol at position {i} is unknown: '{symbol}'. Valid symbols at "
                f"position {i}: {''.join(char for _, char in _FILEMODE_TABLE[i])}"
            )
    return mode


class NfpmContentFileModeField(IntField):
    nfpm_alias = "contents.[].file_info.mode"
    alias: ClassVar[str] = "file_mode"
    help = help_text(
        """
        A file mode as a numeric octal, an string octal, or a symbolic representation.

        NB: In most cases, you should set this field and not rely on the default value.
        Pants only tracks the executable bit for workspace files. So, this field defaults
        to 0o755 for executable files and 0o644 for files that are not executable.

        You may specify the file mode as: an octal, an octal string, or a symbolic string.
        If you specify a numeric octal (not as a string), make sure to include python's
        octal prefix: `0o` like in `0o644`. If you specify the octal as a string,
        the `Oo` prefix is optional (like `644`). If you specify a symbolic file mode string,
        you must provide 9 characters with "-" in place of any absent permissions
        (like `'rw-r--r--'`).

        For example to specify world readable/executable and user writable, these
        are equivalent:

        - `0o755`
        - `'755'`
        - `'rwxr-xr-x'`

        Another example for a file with read/write permissions for only the user:

        - `0o600`
        - `'600'`
        - `'rw-------'`

        Another example for a file with the group sticky bit set:

        - `0o2660`
        - `'2660'`
        - `'rw-rwS---'`

        WARNING: If you forget to include the `0o` prefix on a numeric octal, then
        it will be interpreted as an integer which is probably not what you want.
        For example, `755` (no quotes) will be processed as `0o1363` (symbolically
        that would be '-wxrw--wt') which is probably not what you intended. Pants
        cannot detect errors like this, so be careful to either use a string or
        include the `0o` octal prefix.
        """
    )

    # The octal should be between 0o0000 and 0o7777 (inclusive)
    valid_numbers = ValidNumbers.positive_and_zero

    @classmethod
    def compute_value(cls, raw_value: Optional[Union[int, str]], address: Address) -> Optional[int]:
        if isinstance(raw_value, str):
            try:
                octal_value = int(raw_value, 8)
            except ValueError:
                try:
                    octal_value = _parse_filemode(raw_value)
                except ValueError as e:
                    raise InvalidFieldException(
                        f"The '{cls.alias}' field in target {address} must be "
                        "an octal (like 0o755 or 0o600), "
                        "an octal as a string (like '755' or '600'), "
                        "or a symbolic file mode (like 'rwxr-xr-x' or 'rw-------'). "
                        f"It is set to {repr(raw_value)}."
                    ) from e
            value = super().compute_value(octal_value, address)
        else:
            value = super().compute_value(raw_value, address)
        if value is not None and value > 0o7777:
            raise InvalidFieldException(
                f"The '{cls.alias} field in target {address} must be less than or equal to "
                f"0o7777, but was set to {repr(raw_value)} (ie: `{value:#o}`)."
            )
        return value


class NfpmContentFileMtimeField(StringField):
    nfpm_alias = "contents.[].file_info.mtime"
    alias: ClassVar[str] = "file_mtime"
    default = mtime_default
    help = help_text(
        f"""
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

        The default value is {repr(mtime_default)}. You may also override
        the default value by setting `[nfpm].default_mtime` in `pants.toml`,
        or by setting the `SOURCE_DATE_EPOCH` environment variable.

        See also: https://reproducible-builds.org/docs/timestamps/
        """
    )

    def normalized_value(self, default_mtime: str | None):
        if self.value == self.default and default_mtime and self.value != default_mtime:
            return default_mtime
        return self.value


# -----------------------------------------------------------------------------------------------
# Internal generic parent class fields
# -----------------------------------------------------------------------------------------------


class InvalidFieldMemberTypeException(InvalidFieldException):
    # based on InvalidFieldTypeException
    def __init__(
        self,
        address: Address,
        field_alias: str,
        raw_value: Optional[Any],
        *,
        expected_type: str,
        at_index: int,
        wrong_element: Any,
        description_of_origin: str | None = None,
    ) -> None:
        super().__init__(
            softwrap(
                f"""
                The {repr(field_alias)} field in target {address} must be an iterable with
                elements that have type {expected_type}. Encountered the element `{wrong_element}`
                of type {type(wrong_element)} instead of {expected_type} at index {at_index}:
                `{repr(raw_value)}`
                """
            ),
            description_of_origin=description_of_origin,
        )


class _SrcDstSequenceField(Field):
    # this cannot be a SequenceField as compute_value's use of ensure_list
    # does not work with expected_element_type=tuple when the value itself
    # is already a tuple.
    nfpm_alias = ""
    value: tuple[tuple[str, str], ...]

    # Subclasses must define these
    _dst_alias: ClassVar[str]

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[Iterable[str]]], address: Address
    ) -> tuple[tuple[str, str], ...]:
        src_dst_map = super().compute_value(raw_value, address)
        if not src_dst_map:
            return ()
        if not isinstance(src_dst_map, Iterable):
            raise InvalidFieldTypeException(
                address,
                cls.alias,
                raw_value,
                expected_type="an iterable of 2-string-tuples (tuple[tuple[str, str], ...])",
            )

        def invalid_member_exception(
            at_index: int, wrong_element: Any
        ) -> InvalidFieldMemberTypeException:
            return InvalidFieldMemberTypeException(
                address,
                cls.alias,
                raw_value,
                expected_type="2-string-tuples (tuple[str, str])",
                wrong_element=wrong_element,
                at_index=at_index,
            )

        validated: list[tuple[str, str]] = []
        for i, x in enumerate(src_dst_map):
            if not isinstance(x, Iterable):
                raise invalid_member_exception(i, x)
            element = tuple(x)
            if len(element) != 2:
                raise invalid_member_exception(i, x)
            for s in element:
                if not isinstance(s, str):
                    raise invalid_member_exception(i, x)
            validated.append(cast(tuple[str, str], element))
        src_dst_map = tuple(validated)

        # nFPM normalizes paths to be absolute, so "" is effectively the same as "/".
        # But, this does not validate the paths, leaving it up to nFPM to do any validation
        # that a specific packager might require.

        dst_seen = set()
        dst_dupes = set()
        for src, dst in src_dst_map:
            if dst in dst_seen:
                dst_dupes.add(dst)
            else:
                dst_seen.add(dst)
        if dst_dupes:
            raise InvalidFieldException(
                help_text(
                    lambda: f"""
                    '{cls._dst_alias}' must be unique in '{cls.alias}', but
                    found duplicate entries for: {repr(dst_dupes)}
                    """
                )
            )

        return src_dst_map


class _NfpmContentOverridesField(OverridesField):
    nfpm_alias = ""
    _disallow_overrides_for_field_aliases: tuple[str, ...] = ()

    @classmethod
    def compute_value(
        cls,
        raw_value: Optional[dict[Union[str, tuple[str, ...]], dict[str, Any]]],
        address: Address,
    ) -> Optional[FrozenDict[tuple[str, ...], FrozenDict[str, ImmutableValue]]]:
        value = super().compute_value(raw_value, address)
        if not value:
            return None
        for dst, overrides in value.items():
            for field_alias in cls._disallow_overrides_for_field_aliases:
                if field_alias in overrides:
                    raise InvalidFieldException(
                        help_text(
                            f"""
                            '{cls.alias}' does not support overriding '{field_alias}'.
                            Please remove the '{field_alias}' override for: {dst}
                            """
                        )
                    )
        return value


# -----------------------------------------------------------------------------------------------
# File-specific fields
# -----------------------------------------------------------------------------------------------


class NfpmContentFileSourceField(OptionalSingleSourceField):
    nfpm_alias = ""
    none_is_valid_value = True
    help = help_text(
        lambda: f"""
        A file that should be copied into an nFPM package (optional).

        Either specify a file with '{NfpmContentFileSourceField.alias}', or use
        '{NfpmDependencies.alias}' to add a dependency on the target that owns
        the file.

        If both '{NfpmContentSrcField.alias}' and '{NfpmContentFileSourceField.alias}'
        are populated, then the file in '{NfpmContentFileSourceField.alias}' will be
        placed in the sandbox at the '{NfpmContentSrcField.alias}' path (similar to
        how the '{RelocatedFiles.alias}' target works).
        """
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[str]:
        value_or_default = super().compute_value(raw_value, address)
        # This field should either have a path to a file or it should be None.
        # If it is a path to a file, we rely on standard glob_match_error_behavior
        # to inform the user of any issues finding the file.
        if value_or_default == "":
            # avoid ambiguity so we can use "is None" checks with this field.
            raise InvalidFieldException(
                help_text(
                    f"""\
                    The '{cls.alias}' field in target {address} should not be an empty string.
                    Did you mean to set it to None?
                    """
                )
            )
        return value_or_default


class NfpmContentSrcField(AsyncFieldMixin, StringField):
    nfpm_alias = "contents.[].src"
    alias: ClassVar[str] = "src"
    help = help_text(
        lambda: f"""
        A file path that should be included in the package.

        When the package gets installed, the file from '{NfpmContentSrcField.alias}'
        will be installed using the absolute path in '{NfpmContentDstField.alias}'.

        This path should be relative to the sandbox. The path should point to a
        generated file or a real file sourced from the workspace.

        Either '{NfpmContentSrcField.alias}' or '{NfpmContentFileSourceField.alias}'
        is required. If the '{NfpmContentFileSourceField.alias}' field is provided,
        then the '{NfpmContentSrcField.alias}' defaults to the file referenced in the
        '{NfpmContentFileSourceField.alias}' field.

        If both '{NfpmContentSrcField.alias}' and '{NfpmContentFileSourceField.alias}'
        are populated, then the file in '{NfpmContentFileSourceField.alias}' will be
        placed in the sandbox at the '{NfpmContentSrcField.alias}' path (similar to
        how the '{RelocatedFiles.alias}' target works).
        """
    )

    @property
    def file_path(self) -> str | None:
        """The path to the file, relative to the build root.

        The return type is optional because it's possible to have 0-1 files.
        """
        if self.value is None:
            return None
        return os.path.join(self.address.spec_path, self.value)


class NfpmContentDstField(StringField):
    nfpm_alias = "contents.[].dst"
    alias: ClassVar[str] = "dst"
    required = True
    value: str
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
    # - symlink (handled by a nfpm_content_symlink target)
    file = ""
    config = "config"
    # excluded rpm-specific values


class NfpmContentTypeField(StringField):
    nfpm_alias = "contents.[].type"
    alias: ClassVar[str] = "content_type"
    valid_choices = NfpmContentFileType
    default = NfpmContentFileType.file.value
    value: str  # will not be None due to enum + default
    help = help_text(
        lambda: f"""
        The nFPM content type for the packaged file.

        The content type can be either
          - {repr(NfpmContentFileType.file.value)}: a normal file (the default), or
          - {repr(NfpmContentFileType.config.value)}: a config file.

        This field only supports file-specific nFPM content types.
        Please use these targets for non-file content:
          - For 'dir' content, use targets `nfpm_content_dir` and `nfpm_content_dirs`.
          - For 'symlink' content, use targets `nfpm_content_symlink` and `nfpm_content_symlinks`.

        The nFPM 'tree' content type is not supported. Before passing the list of
        package contents to nFPM, pants expands target generators and any globs,
        so the 'tree' content type does not make sense.
        """
    )


class NfpmContentFilesField(_SrcDstSequenceField):
    alias: ClassVar[str] = "files"
    required = True
    help = help_text(
        lambda: f"""
        A list of 2-tuples ('{NfpmContentSrcField.alias}', '{NfpmContentDstField.alias}').

        The second part, `{NfpmContentDstField.alias}', must be unique across all entries.
        """
    )
    dst_alias = NfpmContentDstField.alias


class NfpmContentFilesOverridesField(_NfpmContentOverridesField):
    help = help_text(
        f"""
        Override the field values for generated `nfpm_content_file` targets.

        This expects a dictionary of '{NfpmContentDstField.alias}' files to a dictionary for the overrides.
        """
    )
    _disallow_overrides_for_field_aliases = (
        NfpmContentFileSourceField.alias,
        NfpmContentSrcField.alias,
        NfpmContentDstField.alias,
    )


# -----------------------------------------------------------------------------------------------
# Symlink-specific fields
# -----------------------------------------------------------------------------------------------


class NfpmContentSymlinkSrcField(NfpmContentSrcField):
    required = True
    value: str
    help = help_text(
        lambda: f"""
        The symlink target path (on package install).

        When the package gets installed, a symlink will be installed at the
        '{NfpmContentSymlinkDstField.alias}' path. The symlink will point to the
        '{NfpmContentSymlinkSrcField.alias}' path (the symlink target).

        This path is a path on the file system where the package will be installed.
        If this path is absolute, it is the absolute path to the symlink's target path.
        If this path is relative, it is relative to the '{NfpmContentSymlinkDstField.alias}'
        path, which is where the symlink will be created.
        """
    )


class NfpmContentSymlinkDstField(NfpmContentDstField):
    required = True
    value: str
    help = help_text(
        lambda: f"""
        The symlink path (on package install).

        When the package gets installed, a symlink will be installed at the
        '{NfpmContentSymlinkDstField.alias}' path. The symlink will point to the
        '{NfpmContentSymlinkSrcField.alias}' path (the symlink target).

        This path is an absolute path on the file system where the package
        will be installed.
        """
    )


class NfpmContentSymlinksField(_SrcDstSequenceField):
    alias: ClassVar[str] = "symlinks"
    required = True
    help = help_text(
        lambda: f"""
        A list of 2-tuples ('{NfpmContentSymlinkSrcField.alias}', '{NfpmContentSymlinkDstField.alias}').

        The second part, `{NfpmContentSymlinkDstField.alias}', must be unique across all entries.
        """
    )
    _dst_alias = NfpmContentSymlinkDstField.alias


class NfpmContentSymlinksOverridesField(_NfpmContentOverridesField):
    help = help_text(
        f"""
        Override the field values for generated `nfpm_content_symlink` targets.

        This expects a dictionary of '{NfpmContentSymlinkDstField.alias}' files
        to a dictionary for the overrides.
        """
    )
    _disallow_overrides_for_field_aliases = (
        NfpmContentSymlinkSrcField.alias,
        NfpmContentSymlinkDstField.alias,
    )


# -----------------------------------------------------------------------------------------------
# Dir-specific fields
# -----------------------------------------------------------------------------------------------


class NfpmContentDirDstField(NfpmContentDstField):
    required = True
    value: str
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
    required = True
    value: tuple[str, ...]
    help = help_text(
        lambda: f"""
        A list of install path for '{NfpmContentDirDstField.alias}' directories.

        When the package gets installed, each directory will be created.

        Each path is an absolute path on the file system where the package
        will be installed.
        """
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[Iterable[str]], address: Address) -> tuple[str, ...]:
        dst_dirs = super().compute_value(raw_value, address)
        assert dst_dirs is not None  # it is required
        # nFPM normalizes paths to be absolute, so "" is effectively the same as "/".
        # But this does not validate the paths, leaving it up to nFPM to do any validation
        # that a specific packager might require.

        dst_seen = set()
        dst_dupes = set()
        for dst in dst_dirs:
            if dst in dst_seen:
                dst_dupes.add(dst)
            else:
                dst_seen.add(dst)
        if dst_dupes:
            raise InvalidFieldException(
                help_text(
                    lambda: f"""
                    '{NfpmContentDirDstField.alias}' must be unique in '{cls.alias}', but
                    found duplicate entries for: {repr(dst_dupes)}
                    """
                )
            )

        return dst_dirs


class NfpmContentDirsOverridesField(_NfpmContentOverridesField):
    help = help_text(
        f"""
        Override the field values for generated `nfpm_content_dir` targets.

        This expects a dictionary of '{NfpmContentDirDstField.alias}' files
        to a dictionary for the overrides.
        """
    )
    _disallow_overrides_for_field_aliases = (NfpmContentDirDstField.alias,)
