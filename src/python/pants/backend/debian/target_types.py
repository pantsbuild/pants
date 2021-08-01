# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.goals.package import OutputPathField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    DictStringToStringField,
    SpecialCasedDependencies,
    StringField,
    Target,
)
from pants.util.docutil import doc_url


class DebianControlFile(StringField):
    alias = "control"
    help = "Path to a Debian control file for the package to be produced."


class DebianSymlinks(DictStringToStringField):
    alias = "symlinks"
    help = "Symlinks to create for each target being packaged."


class DebianInstallPrefix(StringField):
    alias = "install_prefix"
    default = "/opt"
    help = "Absolute path to a directory where Debian package will be installed to."


class DebianPackageDependencies(SpecialCasedDependencies):
    alias = "packages"
    help = (
        "Addresses to any targets that can be built with `./pants package`, e.g. "
        '`["project:app"]`.\n\nPants will build the assets as if you had run `./pants package`. '
        "It will include the results in your Debian package using the same name they would normally have, "
        "but without the `--distdir` prefix (e.g. `dist/`).\n\nYou can include anything that can "
        "be built by `./pants package`, e.g. a `pex_binary`, a `python_distribution`, or a `shell_library`."
    )


class DebianPackage(Target):
    alias = "debian_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        DebianControlFile,
        DebianSymlinks,
        DebianInstallPrefix,
        DebianPackageDependencies,
    )
    help = "A Debian package containing an artifact.\n\n" f"See {doc_url('debian-package')}."
