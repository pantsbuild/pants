# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ClassVar

from pants.backend.nfpm.fields._relationships import NfpmPackageRelationshipsField
from pants.backend.nfpm.fields.all import NfpmDependencies
from pants.backend.nfpm.fields.scripts import NfpmPackageScriptsField
from pants.engine.target import StringField
from pants.util.frozendict import FrozenDict
from pants.util.strutil import help_text

# These fields are used by the `nfpm_archlinux_package` target
# Some fields will be duplicated by other package types which
# allows the help string to be packager-specific.


class NfpmArchlinuxPackagerField(StringField):
    nfpm_alias = "archlinux.packager"
    alias: ClassVar[str] = "packager"
    help = help_text(
        # based in part on the docs at:
        # https://nfpm.goreleaser.com/configuration/#reference
        lambda: f"""
        The name and email address of the packager or packager organization.

        The '{NfpmArchlinuxPackagerField.alias}' is used to identify who actually
        packaged the software, as opposed to the author of the software, or the
        maintainer of an archlinux PKGBUILD.

        The name is first, then the email address inside angle brackets `<>`
        (in RFC5322 format). For example: "Foo Bar <maintainer@example.com>"
        This format is the conventional format; it not a hard requirement.

        If not set, nFPM uses "Unknown Packager" by default (as does `makepkg`).

        See:
        https://man.archlinux.org/man/BUILDINFO.5
        https://wiki.archlinux.org/title/Makepkg#Packager_information
        """
    )
    # nFPM embeds this string as-is in the archlinux package.


class NfpmArchlinuxPkgbaseField(StringField):
    nfpm_alias = "archlinux.pkgbase"
    alias: ClassVar[str] = "pkgbase"
    help = help_text(
        # based in part on the docs at:
        # https://nfpm.goreleaser.com/configuration/#reference
        lambda: f"""
        The base name of an Archlinux package.

        For split packages, '{NfpmArchlinuxPkgbaseField.alias}' specifies the
        name of the group of packages. For all other packages, this is the same
        as package name (known as 'pkgname' by Archlinux packaging tools).
        If unset, nFPM will use the package name as the default value for the
        '{NfpmArchlinuxPkgbaseField.alias}' field.

        See:
        https://man.archlinux.org/man/BUILDINFO.5
        https://wiki.archlinux.org/title/PKGBUILD#pkgbase
        """
    )


class NfpmArchlinuxReplacesField(NfpmPackageRelationshipsField):
    nfpm_alias = "replaces"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        """
        A list of packages that this package replaces or obsoletes.

        This allows for combining packages or splitting them up. When pacman
        does a `sysupgrade` operation, it will immediately replace the listed
        packages with this package. This option is ignored during pacman
        `sync` or `upgrade` operations.

        See:
        https://wiki.archlinux.org/title/PKGBUILD#replaces
        https://man.archlinux.org/man/core/pacman/PKGBUILD.5.en
        """
    )


class NfpmArchlinuxProvidesField(NfpmPackageRelationshipsField):
    nfpm_alias = "provides"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        lambda: f"""
        A list of (virtual) packages or shared libraries that this package provides.

        Each entry can be either a package name or a shared library (which ends
        with ".so"). You can specify a version on both package names and shared
        libraries. If specified, the version must use `=` (not `<`, `<=`, etc).

        Make sure to include any shared libraries (.so files) that this package
        installs if they provide an external API for other packages to use.

        Do not include the 'package_name' (known by 'pkgname' in Archlinux) in
        the list of '{NfpmArchlinuxProvidesField.alias}' as that is implicit.

        For example, package "baz" could declare that it also provides virtual
        packages "foo" and "bar" as well as the "libbaz.so" v2 shared object.
        Because the "baz" package implicitly provides its own name, this list
        should not include "baz".

        - "foo"
        - "bar=1.0.0"
        - "libbaz.so=2"

        If several packages declare the same '{NfpmArchlinuxProvidesField.alias}',
        then they might need to declare that they conflict with each other
        using '{NfpmArchlinuxConflictsField.alias}' if, for example, they also
        install a binary with the same path. Packages that have the same package
        (or virtual package) in both '{NfpmArchlinuxProvidesField.alias}' and
        '{NfpmArchlinuxConflictsField.alias}' are considered alternative packages
        that cannot be installed at the same time. If those package only include
        an entry in '{NfpmArchlinuxProvidesField.alias}' and not in
        '{NfpmArchlinuxConflictsField.alias}', then they CAN be installed at the
        same time.

        See:
        https://wiki.archlinux.org/title/PKGBUILD#provides
        https://man.archlinux.org/man/core/pacman/PKGBUILD.5.en
        https://wiki.archlinux.org/title/Arch_package_guidelines#Package_relations
        """
    )


class NfpmArchlinuxDependsField(NfpmPackageRelationshipsField):
    nfpm_alias = "depends"
    alias: ClassVar[str] = nfpm_alias  # TODO: this might be confused with "dependencies"
    help = help_text(
        lambda: f"""
        List of package dependencies (for package installers).

        The '{NfpmArchlinuxDependsField.alias}' field has install-time dependencies
        that can use version selectors (with one of `<`, `<=`, `=`, `>=`, `>`).

        - "git"
        - "tcpdump<5"
        - "foobar>=1.8.0"

        WARNING: This is NOT the same as the 'dependencies' field!
        It does not accept pants-style dependencies like target addresses.

        See:
        https://wiki.archlinux.org/title/PKGBUILD#depends
        https://man.archlinux.org/man/core/pacman/PKGBUILD.5.en
        https://wiki.archlinux.org/title/Arch_package_guidelines#Package_dependencies
        """
    )


class NfpmArchlinuxConflictsField(NfpmPackageRelationshipsField):
    nfpm_alias = "conflicts"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        lambda: f"""
        A list of (virtual) packages that this package conflicts with.

        Packages that conflict with each other cannot be installed at the same time.

        The '{NfpmArchlinuxConflictsField.alias}' field has the same syntax as the
        '{NfpmArchlinuxDependsField.alias}' field.

        See:
        https://wiki.archlinux.org/title/PKGBUILD#conflicts
        https://man.archlinux.org/man/core/pacman/PKGBUILD.5.en
        """
    )


class NfpmArchlinuxScriptsField(NfpmPackageScriptsField):
    nfpm_aliases: ClassVar[FrozenDict[str, str]] = FrozenDict(
        {
            **NfpmPackageScriptsField.nfpm_aliases,
            "preupgrade": "archlinux.scripts.preupgrade",
            "postupgrade": "archlinux.scripts.postupgrade",
        }
    )
    help = help_text(
        f"""
        Map of install scripts source files for the Archlinux package.

        This maps the script type (key) to the script source file (value).
        Each of the script source file(s) must be provided via '{NfpmDependencies.alias}'.
        nFPM will package all of these scripts in a single `.INSTALL` scriptlet file
        by adding a shell function for each of your script files where your script becomes
        the body of that function. These functions are:

            | nFPM script | `.INSTALL` function |
            +-------------+---------------------+
            | preinstall  | pre_install         |
            | postinstall | post_install        |
            | preupgrade  | pre_upgrade         |
            | postupgrade | post_upgrade        |
            | preremove   | pre_remove          |
            | postremove  | post_remove         |

        So, if you provide a `preinstall` script, the `.INSTALL` scriptlet would contain:

            ```
            function pre_install() {{
            # Your preinstall script's contents get embedded here.
            }}
            ```

        Here are several things to keep in mind when writing your scripts:

        * Your scripts are actually functions, so use `return` instead of `exit`.
        * `pacman` uses `/bin/sh` to source `.INSTALL` and run the function(s).
        * `pacman` runs these in a chroot.
        * The current directory is the root of the chroot.

        Please consult the Archlinux docs to understand when `pacman` will run
        each of these functions and what arguments the functions will receive.

        See:
        https://wiki.archlinux.org/title/pacman#What_happens_during_package_install/upgrade/removal
        https://man.archlinux.org/man/core/pacman/PKGBUILD.5.en#INSTALL/UPGRADE/REMOVE_SCRIPTING
        https://wiki.archlinux.org/title/PKGBUILD#install
        """
    )
