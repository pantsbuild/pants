# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.target import StringField
from pants.util.strutil import help_text

# These fields are used by the `nfpm_rpm_package` target
# Some fields will be duplicated by other package types which
# allows the help string to be packager-specific.


# Internally, nFPM just uses this to populate the default for 'packager'.
# So, there's no point exposing both in our UX.
# class NfpmRpmMaintainerField(StringField):
#     alias = "maintainer"


class NfpmRpmPackagerField(StringField):
    alias = "packager"
    # nFPM uses value of 'maintainer' as default.
    help = help_text(
        # based in part on the docs at:
        # https://nfpm.goreleaser.com/configuration/#reference
        lambda: f"""
        The name and email address of the packager or packager organization.

        The '{NfpmRpmPackagerField.alias}' is used to identify who actually
        packaged the software, as opposed to the author of the software.

        The name is first, then the email address inside angle brackets `<>`
        (in RFC822 format). For example: "Foo Bar <maintainer@example.com>"

        See: https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-inside-tags.html#S3-RPM-INSIDE-PACKAGER-TAG

        N.B.: Packages distributed by Fedora do not use this field.
        https://docs.fedoraproject.org/en-US/packaging-guidelines/#_tags_and_sections
        """
    )
    # TODO: Add validation for the "Name <email@domain>" format


class NfpmRpmVendorField(StringField):
    alias = "vendor"
    help = help_text(
        """
        The entity responsible for packaging (typically an organization).

        See: https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-inside-tags.html#S3-RPM-INSIDE-VENDOR-TAG

        N.B.: Packages distributed by Fedora do not use this field.
        https://docs.fedoraproject.org/en-US/packaging-guidelines/#_tags_and_sections
        """
    )


class NfpmRpmGroupField(StringField):
    alias = "group"
    help = help_text(
        lambda: f"""
        For older rpm-based distros, this groups packages by their functionality.

        '{NfpmRpmGroupField}' is a path-like string to allow for hierarchical
        grouping of applications like "Applications/Editors".

        See: https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-inside-tags.html#S3-RPM-INSIDE-GROUP-TAG

        N.B.: This field is only useful when packaging for old distros (EL 5 or earlier).
        All newer rpm-based distros have deprecated--and do not use--this field.
        https://docs.fedoraproject.org/en-US/packaging-guidelines/#_tags_and_sections
        """
    )


class NfpmRpmSummaryField(StringField):
    alias = "summary"
    help = help_text(
        lambda: f"""
        A one-line description of the packaged software.

        If unset, nFPM will use the first line of 'description' for
        the '{NfpmRpmSummaryField.alias}'.

        See: https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-inside-tags.html#S3-RPM-INSIDE-SUMMARY-TAG
        """
    )
