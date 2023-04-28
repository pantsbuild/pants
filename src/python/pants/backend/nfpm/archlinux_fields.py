# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.target import StringField
from pants.util.strutil import help_text

# These fields are used by the `nfpm_archlinux_package` target
# Some fields will be duplicated by other package types which
# allows the help string to be packager-specific.


class NfpmArchlinuxPackagerField(StringField):
    alias = "packager"
    help = help_text(
        # based in part on the docs at:
        # https://nfpm.goreleaser.com/configuration/#reference
        lambda: f"""
        The name and email address of the packager or packager organization.

        The '{NfpmArchlinuxPackagerField.alias}' is used to identify who actually
        packaged the software, as opposed to the author of the software, or the
        maintainer of an archlinux PKGBUILD.

        The name is first, then the email address inside angle brackets `<>`
        (in RFC822 format). For example: "Foo Bar <maintainer@example.com>"

        If not set, nFPM uses "Unknown Packager" by default (as does `makepkg`).

        See:
        https://man.archlinux.org/man/BUILDINFO.5
        https://wiki.archlinux.org/title/Makepkg#Packager_information
        """
    )
    # TODO: Add validation for the "Name <email@domain>" format


class NfpmArchlinuxPkgbaseField(StringField):
    alias = "pkgbase"
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
