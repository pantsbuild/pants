# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable

from pants.backend.nfpm.target_types import NfpmDebPackage
from pants.engine.addresses import Address
from pants.engine.target import StringField
from pants.engine.unions import UnionRule
from pants.util.strutil import help_text


class DebDistroField(StringField):
    nfpm_alias = ""  # Not an nFPM field
    alias = "distro"
    default = "ubuntu"
    valid_choices = (
        # This has the keys of .deb.search_for_sonames.DISTRO_PACKAGE_SEARCH_URL
        "debian",
        "ubuntu",
    )
    help = help_text(
        """
        The package distribution name (lowercase).

        This is used when injecting package dependencies identified by `native_libs`.

        The valid choices are based on the distros supported by this script:
        `pants.backend.native_libs.deb.search_for_sonames`
        """
    )

    @classmethod
    def compute_value(cls, raw_value: str | None, address: Address) -> str | None:
        if raw_value:
            raw_value = raw_value.lower()
        return super().compute_value(raw_value, address)


class DebDistroCodenameField(StringField):
    nfpm_alias = ""  # Not an nFPM field
    alias = "distro_codename"
    # This is not required to allow rules to inject this field.
    help = help_text(
        """
        The package distribution codename.

        This is used when injecting package dependencies identified by `native_libs`.
        This should be a valid codename for either debian or ubuntu (like bookworm or focal),
        but pants does not validate this field. If it is invalid, the remote search API
        just returns an empty package list.
        """
    )


def rules() -> Iterable[UnionRule]:
    return [
        NfpmDebPackage.register_plugin_field(DebDistroField),
        NfpmDebPackage.register_plugin_field(DebDistroCodenameField),
    ]
