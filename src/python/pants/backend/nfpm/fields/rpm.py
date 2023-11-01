# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import ClassVar, Optional

from pants.backend.nfpm.config import NfpmContent
from pants.backend.nfpm.fields._relationships import NfpmPackageRelationshipsField
from pants.engine.addresses import Address
from pants.engine.target import InvalidFieldException, StringField, StringSequenceField
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
    alias: ClassVar[str] = "packager"
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
    alias: ClassVar[str] = nfpm_alias
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
    alias: ClassVar[str] = "group"
    help = help_text(
        lambda: f"""
        For older rpm-based distros, this groups packages by their functionality.

        '{NfpmRpmGroupField.alias}' is a path-like string to allow for hierarchical
        grouping of applications like "Applications/Editors".

        See: https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-inside-tags.html#S3-RPM-INSIDE-GROUP-TAG

        N.B.: This field is only useful when packaging for old distros (EL 5 or earlier).
        All newer rpm-based distros have deprecated--and do not use--this field.
        https://docs.fedoraproject.org/en-US/packaging-guidelines/#_tags_and_sections
        """
    )


class NfpmRpmSummaryField(StringField):
    nfpm_alias = "rpm.summary"
    alias: ClassVar[str] = "summary"
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
    alias: ClassVar[str] = nfpm_alias
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
    alias: ClassVar[str] = nfpm_alias
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
    alias: ClassVar[str] = nfpm_alias  # TODO: this might be confused with "dependencies"
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
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        lambda: f"""
        List of weak package requirements (for package installers).

        This is like the '{NfpmRpmDependsField.alias}' field, but the package resolver
        can ignore the requirement if it cannot resolve the packages with it included.
        If an entry in '{NfpmRpmRecommendsField.alias}' is ignored, no error or warning gets
        reported.

        The '{NfpmRpmRecommendsField.alias}' field has the same syntax as the
        '{NfpmRpmDependsField.alias}' field.

        See:
        https://rpm-software-management.github.io/rpm/manual/dependencies.html#weak-dependencies
        """
    )


class NfpmRpmSuggestsField(NfpmPackageRelationshipsField):
    nfpm_alias = "suggests"
    alias: ClassVar[str] = nfpm_alias
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
    alias: ClassVar[str] = nfpm_alias
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


class NfpmRpmCompressionAlgorithm(Enum):
    # This is what nFPM implements.
    gzip = "gzip"
    lzma = "lzma"
    xz = "xz"
    zstd = "zstd"


class NfpmRpmCompressionField(StringField):
    nfpm_alias = "rpm.compression"
    alias: ClassVar[str] = "compression"
    valid_choices = NfpmRpmCompressionAlgorithm
    default = f"{NfpmRpmCompressionAlgorithm.gzip.value}:-1"  # same default as nFPM
    help = help_text(
        lambda: f"""
        The compression algorithm to use on the rpm package.

        This takes a compression algorithm and optionally a compression level.
        To specify a level, use 'algorithm:level'. Specifying a compression level
        is only valid for '{NfpmRpmCompressionAlgorithm.gzip.value}' or
        '{NfpmRpmCompressionAlgorithm.zstd.value}'.

        Here are several gzip examples with and without the optional compression level
        (-1 means use the default level which is 5; 9 is the max).

        '{NfpmRpmCompressionAlgorithm.gzip.value}:9'
        '{NfpmRpmCompressionAlgorithm.gzip.value}:0'
        '{NfpmRpmCompressionAlgorithm.gzip.value}:-1'
        '{NfpmRpmCompressionAlgorithm.gzip.value}:5'
        '{NfpmRpmCompressionAlgorithm.gzip.value}'

        Here are several zstd examples. Note that nFPM uses a library that  only
        defines four named compression levels, and then maps the zstd integer
        levels to those. You may specify the zstd level as an integer, or using
        these names: https://github.com/klauspost/compress/tree/master/zstd#status

        '{NfpmRpmCompressionAlgorithm.zstd.value}:fastest'
        '{NfpmRpmCompressionAlgorithm.zstd.value}:default'
        '{NfpmRpmCompressionAlgorithm.zstd.value}:better'
        '{NfpmRpmCompressionAlgorithm.zstd.value}:best'
        '{NfpmRpmCompressionAlgorithm.zstd.value}:3'
        '{NfpmRpmCompressionAlgorithm.zstd.value}:9'
        '{NfpmRpmCompressionAlgorithm.zstd.value}'
        """
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[str]:
        # We only need to do custom computation if raw_value has the optional level.
        if not (isinstance(raw_value, cls.expected_type) and ":" in raw_value):
            # If defined, only algorithm was provided, not level.
            # If not defined, this will apply the default.
            return super().compute_value(raw_value, address)

        # ":" is in raw_value so both an algorithm and level were provided.
        raw_algorithm, level, *unknown = raw_value.split(":")

        # This will check algorithm against the algorithm Enum.
        computed_algorithm = super().compute_value(raw_algorithm, address)
        if computed_algorithm not in ("gzip", "zstd"):
            raise InvalidFieldException(
                f"Values for the '{cls.alias}' field in target {address} "
                "may only specify a compression level for gzip or zstd compression, "
                f"but {repr(computed_algorithm)} was provided as {repr(raw_value)}."
            )

        if unknown:
            raise InvalidFieldException(
                f"Values for the '{cls.alias}' field in target {address} "
                f"must not have more than one ':', but got {len(unknown) + 1}."
                "Only use ':' to specify an optional compression level after "
                "the compression algorithm (ie '<algorithm>[:<level>]')."
            )

        # Pass level as-is w/o sanitization or type checking because
        # there are too many possible levels to check it sanely here.
        return f"{computed_algorithm}:{level}"


class NfpmRpmGhostContents(StringSequenceField):
    nfpm_alias = ""  # does not map directly to a nfpm.yaml field
    alias = "ghost_contents"
    help = help_text(
        """
        A list of files that this package owns, but that this package does not include.

        Examples of ghosted files include:
        - A log file or a state file that does not exist until runtime.
        - A binary that is managed by 'alternatives'.

        RPM specs use the `%ghost` directive to list these ghosted files.

        Each file in this list gets passed to nFPM via the 'contents' field with
        'type=ghost'. Then nFPM translates that into the appropriate RPM header.
        The file does not need to exist in your pants workspace as nFPM directly
        adds it to the RPM header.

        See: https://ftp.osuosl.org/pub/rpm/max-rpm/s1-rpm-inside-files-list-directives.html#S3-RPM-INSIDE-FLIST-GHOST-DIRECTIVE

        N.B.: Packages distributed by Fedora must use this if they provide 'alternatives'.
        https://docs.fedoraproject.org/en-US/packaging-guidelines/Alternatives/#_how_to_use_alternatives
        """
    )
    # TODO: does this need any validation like requiring absolute paths?

    @property
    def nfpm_contents(self) -> list[NfpmContent]:
        contents = [NfpmContent(type="ghost", dst=ghost) for ghost in self.value or ()]
        return contents
