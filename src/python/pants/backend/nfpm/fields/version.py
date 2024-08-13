# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ClassVar

from pants.engine.target import IntField, StringField
from pants.util.strutil import help_text


class NfpmVersionField(StringField):
    nfpm_alias = "version"
    alias: ClassVar[str] = nfpm_alias
    required = True
    help = help_text(
        # Based in part on the docs from:
        # https://nfpm.goreleaser.com/configuration/#reference
        lambda: f"""
        The package version (preferably following semver).

        If '{NfpmVersionSchemaField.alias}' is not 'semver', then this
        should not be prefixed with a 'v' because some package managers,
        like deb, require the version start with a digit.

        See the '{NfpmVersionSchemaField.alias}' field's help for more
        details about how this field gets parsed by nFPM when it is 'semver'.
        """
    )


class NfpmVersionSchemaField(StringField):
    nfpm_alias = "version_schema"
    alias: ClassVar[str] = nfpm_alias
    default = "semver"
    valid_choices = ("none", "semver")
    help = help_text(
        # Based in part on the docs from:
        # https://nfpm.goreleaser.com/configuration/#reference
        lambda: f"""
        Which schema the '{NfpmVersionField.alias}' field follows.

        nFPM only supports two schemas for now: semver, none

        If this is "none", then nFPM will use '{NfpmVersionField.alias}' as-is.

        If this is "semver", then nFPM will parse '{NfpmVersionField.alias}'
        into its constituent parts using a lenient algorithm: It will strip
        a `v` prefix and will accept versions with fewer than 3 components,
        like `v1.2`. If parsing fails, then the version is used as-is.
        If parsing succeeds, nFPM replaces config options with the parsed
        components.

        The '{NfpmVersionField.alias}' field always gets replaced with a dotted
        3 part version (Major.Minor.Patch).

        The '{NfpmVersionPrereleaseField.alias}' field is only updated if not set.
        It gets the "dev", "alpha", "rc", or similar parsed prerelease indicator.

        The '{NfpmVersionMetadataField.alias}' field is only updated if not set.
        This will be set with "git" when the version contains "+git" and similar
        metadata tags.

        The '{NfpmVersionReleaseField.alias}' and '{NfpmVersionEpochField.alias}' fields are NOT
        replaced by components parsed from '{NfpmVersionField.alias}'.

        N.B.: Some of these fields are not available for all package types.

        This field is named "{NfpmVersionField.alias}" because that is the term
        used by nFPM. Though deb and rpm packaging also use "version", this is
        known as "pkgver" in apk and archlinux packaging.
        """
    )


class NfpmVersionPrereleaseField(StringField):
    nfpm_alias = "prerelease"
    # nFPM calls this "prerelease", but we prefix with "version_" to
    # highlight this field's relationship with the other version_ fields.
    alias: ClassVar[str] = "version_prerelease"
    help = help_text(
        lambda: f"""
        This is a pre-release indicator like "alpha" or "beta" and often includes
        a numeric component like "rc1" and "rc2".

        For apk and archlinux, version and prerelease are merely concatenated.
        For deb and rpm, prerelease is typically prefixed with a "~" in the version.

        nFPM extracts the default for this from '{NfpmVersionField.alias}'
        if it is semver compatible. If you set '{NfpmVersionPrereleaseField.alias}',
        then any prerelease component of '{NfpmVersionField.alias}' gets discarded.
        """
    )


class NfpmVersionMetadataField(StringField):
    nfpm_alias = "version_metadata"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        lambda: f"""
        This is package-manager specific metadata for the version.

        This is typically prefixed with a "+" in the version. If the version
        contains "+git", then the '{NfpmVersionMetadataField.alias}' is "git".
        Debian has various conventions for this metadata, including things like
        "+b", "+nmu", "+really", and "+deb10u1". See:
        https://www.debian.org/doc/debian-policy/ch-controlfields.html#special-version-conventions

        nFPM extracts the default for this from '{NfpmVersionField.alias}'
        if it is semver compatible. If you set '{NfpmVersionMetadataField.alias}',
        then any metadata component of '{NfpmVersionField.alias}' gets discarded.
        """
    )


class NfpmVersionReleaseField(IntField):
    nfpm_alias = "release"
    # nFPM calls this "release", but we prefix with "version_" to
    # highlight this field's relationship with the other version_ fields.
    alias: ClassVar[str] = "version_release"
    default = 1
    help = help_text(
        lambda: f"""
        The release or revision number for a given package version.

        Increment the release each time you release the same version of the
        package. Often, these releases allow for correcting metadata about
        a package or to rebuild something that was broken in a previous release
        of that version.

        Reset this to 1 whenever you bump the '{NfpmVersionField.alias}' field.

        N.B.: nFPM does NOT parse this from the '{NfpmVersionField.alias}' field.
        """
    )


class NfpmVersionEpochField(IntField):
    nfpm_alias = "epoch"
    # nFPM calls this "epoch", but we prefix with "version_" to
    # highlight this field's relationship with the other version_ fields.
    alias: ClassVar[str] = "version_epoch"
    help = help_text(
        lambda: f"""
        A package with a higher version epoch will always be considered newer.
        This is primarily useful when the version numbering scheme has changed.

        Debian and RPM documentation warn against using epoch in most cases:
        https://www.debian.org/doc/debian-policy/ch-controlfields.html#epochs-should-be-used-sparingly
        https://rpm-packaging-guide.github.io/#epoch

        When this field is None (the default) nFPM will use "" for deb packages,
        and "0" for rpm packages.

        N.B.: The nFPM documentation incorrectly notes that nFPM can parse this
        from the '{NfpmVersionField.alias}' field; the nFPM code actually does
        not replace or update this.
        """
    )
