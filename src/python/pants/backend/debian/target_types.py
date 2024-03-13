# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pathlib import PurePath
from typing import Sequence

from pants.core.goals.package import OutputPathField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    DictStringToStringField,
    InvalidFieldException,
    MultipleSourcesField,
    SpecialCasedDependencies,
    StringField,
    Target,
)
from pants.util.docutil import bin_name, doc_url
from pants.util.strutil import help_text, softwrap


class DebianSources(MultipleSourcesField):
    required = True
    help = help_text(
        """
        Paths that will be included in the package to be produced such as Debian metadata files.
        You must include a DEBIAN/control file.

        Paths are relative to the BUILD file's directory and all paths must belong to the same parent directory.
        For example, `sources=['dir/**']` is valid, but `sources=['top_level_file.txt']`
        and `sources=['dir1/*', 'dir2/*']` are not.
        """
    )

    def validate_resolved_files(self, files: Sequence[str]) -> None:
        """Check that all files are coming from the same directory."""
        super().validate_resolved_files(files)
        if not files:
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The `{self.alias}` field in target `{self.address}` must
                    resolve to at least one file.
                    """
                )
            )

        files_outside_dirs = [f for f in files if len(PurePath(f).parts) == 1]
        if files_outside_dirs:
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The `{self.alias}` field in target `{self.address}` must be paths to
                    files in a single sources directory. Individual files
                    were found: {files_outside_dirs}
                    """
                )
            )

        directory_prefixes = {PurePath(f).parts[0] for f in files}
        if len(directory_prefixes) > 1:
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The `{self.alias}` field in target `{self.address}` must be paths to
                    files in a single sources directory. Multiple directories
                    were found: {directory_prefixes}
                    """
                )
            )


class DebianSymlinks(DictStringToStringField):
    alias = "symlinks"
    help = help_text(
        """
        Symlinks to create for each target being packaged.

        For example, you could set symlinks={'command-name': 'entrypoint-name'}.
        """
    )


class DebianInstallPrefix(StringField):
    alias = "install_prefix"
    default = "/opt"
    help = "Absolute path to a directory where Debian package will be installed to."


class DebianPackageDependencies(SpecialCasedDependencies):
    alias = "packages"
    required = True
    help = help_text(
        f"""
        Addresses to any targets that can be built with `{bin_name()} package`, e.g.
        `["project:app"]`.

        Pants will build the assets as if you had run `{bin_name()} package`.
        It will include the results in your Debian package using the same name they would normally have,
        but without the `--distdir` prefix (e.g. `dist/`).

        You can include anything that can be built by `{bin_name()} package`, e.g. a `pex_binary`,
        a `python_distribution`, or an `archive`.
        """
    )


class DebianPackage(Target):
    alias = "debian_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        DebianSources,
        DebianSymlinks,
        DebianInstallPrefix,
        DebianPackageDependencies,
    )
    help = help_text(
        f""""
        A Debian package containing an artifact.

        This will not install the package, only create a .deb file
        that you can then distribute and install, e.g. via dpkg.

        "See {doc_url('debian-package')}.
        """
    )
