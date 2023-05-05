# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.nfpm.fields._relationships import NfpmPackageRelationshipsField
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
    nfpm_alias = "rpm.packager"
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
    nfpm_alias = "vendor"
    alias = nfpm_alias
    help = help_text(
        """
        The entity responsible for packaging (typically an organization).

        See: https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-inside-tags.html#S3-RPM-INSIDE-VENDOR-TAG

        N.B.: Packages distributed by Fedora do not use this field.
        https://docs.fedoraproject.org/en-US/packaging-guidelines/#_tags_and_sections
        """
    )


class NfpmRpmGroupField(StringField):
    nfpm_alias = "rpm.group"
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
    nfpm_alias = "rpm.summary"
    alias = "summary"
    help = help_text(
        lambda: f"""
        A one-line description of the packaged software.

        If unset, nFPM will use the first line of 'description' for
        the '{NfpmRpmSummaryField.alias}'.

        See: https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-inside-tags.html#S3-RPM-INSIDE-SUMMARY-TAG
        """
    )


class NfpmRpmReplacesField(NfpmPackageRelationshipsField):
    nfpm_alias = "replaces"
    alias = nfpm_alias
    help = help_text(
        lambda: f"""
        A list of packages that this package obsoletes (replaces).

        When a pacakge name changes or splits, rpm uses "obsoletes" (ie the
        '{NfpmRpmReplacesField.alias}' field) on the new package to list the old
        package name(s) that can be upgraded to this package.

        The rpm file header uses the term "obsoletes" for this. This field is
        named "{NfpmRpmReplacesField.alias}" because that is the term used by nFPM.

        See:
        https://rpm-software-management.github.io/rpm/manual/dependencies.html#obsoletes
        """
    )


class NfpmRpmProvidesField(NfpmPackageRelationshipsField):
    nfpm_alias = "provides"
    alias = nfpm_alias
    help = help_text(
        lambda: f"""
        A list of virtual packages or file paths that this package provides.

        This is used so that multiple packages can be be alternatives for each other.
        The list can include virtual package names and/or file paths. For example
        the `bash` package includes these in '{NfpmRpmProvidesField.alias}':

        - "bash"
        - "/bin/sh"
        - "/bin/bash"

        This means another package could also provide alternative implementations for
        the "bash" package name and could provide "/bin/sh" and/or "/bin/bash".

        N.B.: Virtual package names must not include any version numbers.

        See:
        https://rpm-software-management.github.io/rpm/manual/dependencies.html#provides
        https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-depend-manual-dependencies.html#S2-RPM-DEPEND-PROVIDES-TAG
        """
    )


class NfpmRpmDependsField(NfpmPackageRelationshipsField):
    nfpm_alias = "depends"
    alias = nfpm_alias  # TODO: this might be confused with "dependencies"
    help = help_text(
        lambda: f"""
        List of package requirements (for package installers).

        The '{NfpmRpmDependsField.alias}' field has install-time requirements that can
        use version selectors (with one of `<`, `<=`, `=`, `>=`, `>` surrounded by
        spaces), where the version is formatted: `[epoch:]version[-release]`

        - "git"
        - "bash < 5"
        - "perl >= 9:5.00502-3"

        The rpm file header uses the term "requires" for this. This field is
        named "{NfpmRpmDependsField.alias}" because that is the term used by nFPM.

        WARNING: This is NOT the same as the 'dependencies' field!
        It does not accept pants-style dependencies like target addresses.

        See:
        https://rpm-software-management.github.io/rpm/manual/dependencies.html#requires
        https://rpm-software-management.github.io/rpm/manual/dependencies.html#versioning
        https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-inside-tags.html#S3-RPM-INSIDE-REQUIRES-TAG
        https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-depend-manual-dependencies.html#S2-RPM-DEPEND-REQUIRES-TAG
        """
    )


class NfpmRpmRecommendsField(NfpmPackageRelationshipsField):
    nfpm_alias = "recommends"
    alias = nfpm_alias
    help = help_text(
        lambda: f"""
        List of weak package requirements (for package installers).

        This is like the '{NfpmRpmDependsField.alias}' field, but the package resolver
        can ignore the requirement if it cannot resolve the packages with it included.
        If an entry in '{NfpmRpmRecommendsField}' is ignored, no error or warning gets
        reported.

        The '{NfpmRpmRecommendsField.alias}' field has the same syntax as the
        '{NfpmRpmDependsField.alias}' field.

        See:
        https://rpm-software-management.github.io/rpm/manual/dependencies.html#weak-dependencies
        """
    )


class NfpmRpmSuggestsField(NfpmPackageRelationshipsField):
    nfpm_alias = "suggests"
    alias = nfpm_alias
    help = help_text(
        lambda: f"""
        List of very weak package requirements (for package installers).

        These suggestions are ignored by the package resolver. They are merely shown
        to the user as optional packages that the user might want to also install.

        The '{NfpmRpmSuggestsField.alias}' field has the same syntax as the
        '{NfpmRpmDependsField.alias}' field.

        See:
        https://rpm-software-management.github.io/rpm/manual/dependencies.html#weak-dependencies
        """
    )


class NfpmRpmConflictsField(NfpmPackageRelationshipsField):
    nfpm_alias = "conflicts"
    alias = nfpm_alias
    help = help_text(
        lambda: f"""
        A list of packages that this package conflicts with.

        Packages that conflict with each other cannot be installed at the same time.

        The '{NfpmRpmConflictsField.alias}' field has the same syntax as the
        '{NfpmRpmDependsField.alias}' field.

        See:
        https://rpm-software-management.github.io/rpm/manual/dependencies.html#conflicts
        https://docs.fedoraproject.org/en-US/packaging-guidelines/Conflicts/
        https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-inside-tags.html#S3-RPM-INSIDE-CONFLICTS-TAG
        https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-depend-manual-dependencies.html#S2-RPM-DEPEND-CONFLICTS-TAG
        """
    )
