# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import Dict, Iterable, Optional, Tuple

from pants.backend.nfpm.fields._relationships import NfpmPackageRelationshipsField
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
    alias = nfpm_alias
    required = True  # Not setting this is deprecated in nFPM, so we require it.
    help = help_text(
        lambda: f"""
        The name and email address of the package maintainer.

        The '{NfpmDebMaintainerField.alias}' is used to identify who actually
        packaged the software, as opposed to the author of the software.

        The name is first, then the email address inside angle brackets `<>`
        (in RFC822 format). For example: "Foo Bar <maintainer@example.com>"

        See: https://www.debian.org/doc/debian-policy/ch-controlfields.html#maintainer
        """
    )
    # TODO: Add validation for the "Name <email@domain>" format


class NfpmDebSectionField(StringField):
    nfpm_alias = "section"
    alias = nfpm_alias
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
    alias = nfpm_alias
    valid_choices = DebPriority
    default = DebPriority.optional.value
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
    alias = "fields"
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
    alias = "triggers"
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
        cls, raw_value: Optional[Dict[str, Iterable[str]]], address: Address
    ) -> Optional[FrozenDict[str, Tuple[str, ...]]]:
        value_or_default = super().compute_value(raw_value, address)
        # only certain keys are allowed in this dictionary.
        if value_or_default and not cls.valid_keys.issuperset(value_or_default.keys()):
            invalid_keys = value_or_default.keys() - cls.valid_keys
            raise InvalidFieldException(
                f"Each key for the {repr(cls.alias)} field in target {address} must be one of"
                f"{repr(cls.valid_keys)}, but {repr(invalid_keys)} was provided.",
            )
        return value_or_default


class NfpmDebReplacesField(NfpmPackageRelationshipsField):
    nfpm_alias = "replaces"
    alias = nfpm_alias
    help = help_text(
        lambda: f"""
        """
    )


class NfpmDebProvidesField(NfpmPackageRelationshipsField):
    nfpm_alias = "provides"
    alias = nfpm_alias
    help = help_text(
        lambda: f"""
        """
    )


class NfpmDebDependsField(NfpmPackageRelationshipsField):
    nfpm_alias = "depends"
    alias = nfpm_alias  # TODO: this might be confused with "dependencies"
    help = help_text(
        lambda: f"""
        """
    )


class NfpmDebRecommendsField(NfpmPackageRelationshipsField):
    nfpm_alias = "recommends"
    alias = nfpm_alias
    help = help_text(
        lambda: f"""
        """
    )


class NfpmDebSuggestsField(NfpmPackageRelationshipsField):
    nfpm_alias = "suggests"
    alias = nfpm_alias
    help = help_text(
        lambda: f"""
        """
    )


class NfpmDebConflictsField(NfpmPackageRelationshipsField):
    nfpm_alias = "conflicts"
    alias = nfpm_alias
    help = help_text(
        lambda: f"""
        """
    )


class NfpmDebBreaksField(NfpmPackageRelationshipsField):
    nfpm_alias = "deb.breaks"
    alias = "breaks"
    help = help_text(
        lambda: f"""
        """
    )
