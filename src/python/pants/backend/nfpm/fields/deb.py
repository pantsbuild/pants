# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import ClassVar, Iterable, Optional

from pants.backend.nfpm.fields._relationships import NfpmPackageRelationshipsField
from pants.backend.nfpm.fields.all import NfpmDependencies
from pants.backend.nfpm.fields.scripts import NfpmPackageScriptsField
from pants.engine.addresses import Address
from pants.engine.target import (
    DictStringToStringField,
    DictStringToStringSequenceField,
    InvalidFieldException,
    StringField,
)
from pants.util.frozendict import FrozenDict
from pants.util.strutil import help_text

# These fields are used by the `nfpm_deb_package` target
# Some fields will be duplicated by other package types which
# allows the help string to be packager-specific.


class NfpmDebMaintainerField(StringField):
    nfpm_alias = "maintainer"
    alias: ClassVar[str] = nfpm_alias
    required = True  # Not setting this is deprecated in nFPM, so we require it.
    value: str
    help = help_text(
        lambda: f"""
        The name and email address of the package maintainer.

        The '{NfpmDebMaintainerField.alias}' is used to identify who actually
        packaged the software, as opposed to the author of the software.

        The name is first, then the email address inside angle brackets `<>`
        (in RFC5322 format). For example: "Foo Bar <maintainer@example.com>"

        See: https://www.debian.org/doc/debian-policy/ch-controlfields.html#maintainer
        """
    )
    # nFPM embeds this string as-is in the deb package.


class NfpmDebSectionField(StringField):
    nfpm_alias = "section"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        """
        Which section, or application area, this package is part of.

        For example, you could classify your application under the "education"
        section, or under a language section like "python", "rust", or "ruby".

        See: https://www.debian.org/doc/debian-policy/ch-archive.html#sections

        Valid sections are listed here:
        https://www.debian.org/doc/debian-policy/ch-archive.html#s-subsections
        """
    )


class DebPriority(Enum):
    # based on https://www.debian.org/doc/debian-policy/ch-archive.html#priorities
    required = "required"
    important = "important"
    standard = "standard"
    optional = "optional"
    extra = "extra"  # Debian notes that this is deprecated and equivalent to optional.


class NfpmDebPriorityField(StringField):
    nfpm_alias = "priority"
    alias: ClassVar[str] = nfpm_alias
    valid_choices = DebPriority
    default = DebPriority.optional.value
    value: str  # will not be None due to enum + default
    help = help_text(
        """
        Indicates how important the package is for OS functions.

        Most packages should just stick with the default priority: "optional".

        See: https://www.debian.org/doc/debian-policy/ch-archive.html#s-f-priority

        Valid priorities are listed here:
        https://www.debian.org/doc/debian-policy/ch-archive.html#priorities
        """
    )


class NfpmDebFieldsField(DictStringToStringField):
    nfpm_alias = "deb.fields"
    alias: ClassVar[str] = "fields"
    help = help_text(
        # based in part on the docs at:
        # https://nfpm.goreleaser.com/configuration/#reference
        lambda: f"""
        Additional fields for the control file. Empty fields are ignored.

        Debian control files supports more fields than the options that are
        exposed by nFPM and the pants nfpm backend. Debian even allows for
        user-defined fields. So, this '{NfpmDebFieldsField.alias}' field
        provides a way to add any additional fields to the debian control file.

        See: https://www.debian.org/doc/debian-policy/ch-controlfields.html#user-defined-fields
        """
    )


class NfpmDebTriggersField(DictStringToStringSequenceField):
    nfpm_alias = "deb.triggers"
    alias: ClassVar[str] = "triggers"
    help = help_text(
        """
        Custom deb triggers.

        nFPM uses this to create a deb triggers file, so that the package
        can declare its "interest" in named triggers or declare that the
        indicated triggers should "activate" when this package's state changes.

        The Debian documentation describes the format for the triggers file.
        nFPM simplifies that by accepting a dictionary from trigger directives
        to lists of trigger names.

        For example (note the underscore in "interest_noawait"):

        `triggers={"interest_noawait": ["some-trigger", "other-trigger"]}`

        Gets translated by nFPM into:

        ```
        interest-noawait some-trigger
        interest-noawait other-trigger
        ```

        See:
        https://wiki.debian.org/DpkgTriggers
        https://www.mankier.com/5/deb-triggers
        """
    )
    valid_keys = {
        # nFPM uses "_" even though the actual triggers file uses "-".
        "interest",
        "interest_await",
        "interest_noawait",
        "activate",
        "activate_await",
        "activate_noawait",
    }

    @classmethod
    def compute_value(
        cls, raw_value: Optional[dict[str, Iterable[str]]], address: Address
    ) -> Optional[FrozenDict[str, tuple[str, ...]]]:
        value_or_default = super().compute_value(raw_value, address)
        # only certain keys are allowed in this dictionary.
        if value_or_default and not cls.valid_keys.issuperset(value_or_default.keys()):
            invalid_keys = value_or_default.keys() - cls.valid_keys
            raise InvalidFieldException(
                f"Each key for the '{cls.alias}' field in target {address} must be one of"
                f"{repr(cls.valid_keys)}, but {repr(invalid_keys)} was provided.",
            )
        return value_or_default


class NfpmDebReplacesField(NfpmPackageRelationshipsField):
    nfpm_alias = "replaces"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        lambda: f"""
        A list of packages that this package replaces or partially replaces.

        To declare that this package partially replaces another package, by
        taking ownership of files in that package, include that other package in
        both '{NfpmDebReplacesField.alias}' and '{NfpmDebBreaksField.alias}'.

        If this package completely replaces the other package, you can force its
        removal by including the other package in both '{NfpmDebReplacesField.alias}'
        and '{NfpmDebConflictsField.alias}' (and '{NfpmDebProvidesField.alias}' if it
        is a virtual package).

        See: https://www.debian.org/doc/debian-policy/ch-relationships.html#overwriting-files-and-replacing-packages-replaces
        """
    )


class NfpmDebProvidesField(NfpmPackageRelationshipsField):
    nfpm_alias = "provides"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        lambda: f"""
        A list of virtual packages that this package provides.

        Each entry can be either a package name, or a package name with a version.
        The version, however, must be declared with `=` (not `<<`, `<=`, etc)

        For example, these declare virtual packages foo and bar.

        - "foo"
        - "bar (=1.0.0)"

        If several packages declare the same '{NfpmDebProvidesField.alias}',
        then they might need to declare that they conflict with each other
        using '{NfpmDebConflictsField.alias}' if, for example, they also install
        a binary with the same path.

        See: https://www.debian.org/doc/debian-policy/ch-relationships.html#virtual-packages-provides
        """
    )


class NfpmDebDependsField(NfpmPackageRelationshipsField):
    nfpm_alias = "depends"
    alias: ClassVar[str] = nfpm_alias  # TODO: this might be confused with "dependencies"
    help = help_text(
        lambda: f"""
        List of package dependencies (for package installers).

        The '{NfpmDebDependsField.alias}' field has install-time dependencies
        that can use version selectors (with one of `<<`, `<=`, `=`, `>=`, `>>`
        in parentheses) or use `|` to specify package alternatives that equally
        satisfy a dependency.

        - "git"
        - "libc6 (>= 2.2.1)"
        - "default-mta | mail-transport-agent"

        Make sure to include package dependencies of this package as well as any
        packages required by the `postinstall`, `postupgrade`, or `preremove` scripts.

        WARNING: This is NOT the same as the 'dependencies' field!
        It does not accept pants-style dependencies like target addresses.

        See: https://www.debian.org/doc/debian-policy/ch-relationships.html
        """
    )


class NfpmDebPreDependsField(NfpmPackageRelationshipsField):
    nfpm_alias = "deb.predepends"
    alias: ClassVar[str] = "predepends"
    help = help_text(
        lambda: f"""
        List of package unpack-time dependencies (for package installers).

        In most cases, you should use the '{NfpmDebDependsField.alias}' field
        instead of this one to declare install-time package dependencies.
        The '{NfpmDebPreDependsField.alias}' field has install-time dependencies
        that need to be available (including unpacking, pre-install, and
        post-install scripts) before unpacking or installing this package.

        Make sure to include packages required by the `preinst` script.

        WARNING: This is NOT the same as the 'dependencies' field!
        It does not accept pants-style dependencies like target addresses.

        See: https://www.debian.org/doc/debian-policy/ch-relationships.html
        """
    )


class NfpmDebRecommendsField(NfpmPackageRelationshipsField):
    nfpm_alias = "recommends"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        lambda: f"""
        List of optional package dependencies (for package installers).

        The '{NfpmDebRecommendsField.alias}' field has packages that can be
        excluded in "unusual installations" but should generally be installed
        with this package.

        WARNING: This is NOT the same as the 'dependencies' field!
        It does not accept pants-style dependencies like target addresses.

        See: https://www.debian.org/doc/debian-policy/ch-relationships.html
        """
    )


class NfpmDebSuggestsField(NfpmPackageRelationshipsField):
    nfpm_alias = "suggests"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        """
        A list of package suggestions (for package installers).

        These packages are completely optional, but could be useful for users
        of this package to install as well.

        See: https://www.debian.org/doc/debian-policy/ch-relationships.html
        """
    )


class NfpmDebConflictsField(NfpmPackageRelationshipsField):
    nfpm_alias = "conflicts"
    alias: ClassVar[str] = nfpm_alias
    help = help_text(
        lambda: f"""
        A list of packages that this package conflicts with.

        Generally, you should use '{NfpmDebBreaksField.alias}' instead of
        '{NfpmDebConflictsField.alias}', because '{NfpmDebConflictsField.alias}'
        imposes much more strict requirements on the order of package installs
        and removals. Use this if the conflicting packages must be completely
        uninstalled before this package can be installed.

        For example, this is how to declare that this package conflicts with the
        foo (version 2.5 or less) and bar packages, so they must be uninstalled
        before this package can be installed.

        - "foo (<2.6)"
        - "bar"

        See: https://www.debian.org/doc/debian-policy/ch-relationships.html#conflicting-binary-packages-conflicts
        """
    )


class NfpmDebBreaksField(NfpmPackageRelationshipsField):
    nfpm_alias = "deb.breaks"
    alias: ClassVar[str] = "breaks"
    help = help_text(
        lambda: f"""
        A list of packages which would break if this package would be installed.

        The installation of this package is blocked (by package installers)
        if any packages in this list are already installed. This is a looser
        package relationship than the '{NfpmDebConflictsField.alias}' field,
        because it allows the package installer more flexibility on ordering
        package installs and removals (For example, if this package breaks "bar",
        then "bar" can be removed after this package when it gets removed in the
        same package install transaction).

        For example, this is how to declare that this breaks package foo, but
        only if foo version 2.5 or less is installed and it breaks package bar
        no matter what version is installed.

        - "foo (<2.6)"
        - "bar"

        See: https://www.debian.org/doc/debian-policy/ch-relationships.html#packages-which-break-other-packages-breaks
        """
    )


class NfpmDebCompressionAlgorithm(Enum):
    # This is what nFPM implements.
    gzip = "gzip"
    none = "none"
    xz = "xz"
    zstd = "zstd"


class NfpmDebCompressionField(StringField):
    nfpm_alias = "deb.compression"
    alias: ClassVar[str] = "compression"
    valid_choices = NfpmDebCompressionAlgorithm
    default = NfpmDebCompressionAlgorithm.gzip.value  # same default as nFPM
    value: str  # will not be None due to enum + default
    help = help_text(
        """
        The compression algorithm to use on the deb package.
        """
    )


class NfpmDebScriptsField(NfpmPackageScriptsField):
    nfpm_aliases: ClassVar[FrozenDict[str, str]] = FrozenDict(
        {
            **NfpmPackageScriptsField.nfpm_aliases,
            "rules": "deb.scripts.rules",
            "templates": "deb.scripts.templates",
            "config": "deb.scripts.config",
        }
    )
    help = help_text(
        f"""
        Map of maintainer script source files for the deb package.

        This maps the script type (key) to the script source file (value).
        Each of the script source file(s) must be provided via '{NfpmDependencies.alias}'.
        The script types are the names used by nFPM. For reference, Debian
        uses the following file names instead:

            | nFPM script | Debian file |
            +-------------+-------------+
            | preinstall  | preinst     |
            | postinstall | postinst    |
            | preremove   | prerm       |
            | postremove  | postrm      |
            | config      | config      |
            | templates   | templates   |
            | rules       | rules       |

        The `pre*` and `post*` scripts are used by `dpkg` at various stages of
        installing, upgrading, and removing the deb package.

        The `config` script and `templates` file are part of the Debian Configuration
        Management Specification. `config` can run at any time, including before
        `preinst` to prompt the user for package configuration using `debconf`.
        `templates` is used by `debconf` to create those prompts.

        The `rules` script is only needed for source packages. This script is an
        executable makefile that can build a binary from the packaged sources.

        Please consult the Debian docs to understand when `dpkg` or `debconf` will
        run each of these scripts, what assumptions you can safely make when they run,
        and how `dpkg` handles a failure.

        See:
        https://www.debian.org/doc/debian-policy/ch-binary.html#maintainer-scripts
        https://www.debian.org/doc/debian-policy/ch-maintainerscripts.html
        https://www.debian.org/doc/debian-policy/ap-flowcharts.html
        http://www.fifi.org/doc/debconf-doc/tutorial.html
        https://www.debian.org/doc/debian-policy/ch-source.html#s-debianrules
        """
    )
