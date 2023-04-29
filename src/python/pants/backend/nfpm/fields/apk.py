# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.target import StringField
from pants.util.strutil import help_text

# These fields are used by the `nfpm_apk_package` target
# Some fields will be duplicated by other package types which
# allows the help string to be packager-specific.


class NfpmApkMaintainerField(StringField):
    nfpm_alias = "maintainer"
    alias = nfpm_alias
    help = help_text(
        # based in part on the docs at:
        # https://nfpm.goreleaser.com/configuration/#reference
        lambda: f"""
        The name and email address of the packager or packager organization.

        The '{NfpmApkMaintainerField.alias}' is used to identify who actually
        packaged the software, as opposed to the author of the software.

        The name is first, then the email address inside angle brackets `<>`
        (in RFC822 format). For example: "Foo Bar <maintainer@example.com>"

        See: https://wiki.alpinelinux.org/wiki/Apk_spec#PKGINFO_Format
        """
    )
    # TODO: Add validation for the "Name <email@domain>" format
