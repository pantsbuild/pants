# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum

from pants.engine.target import StringField
from pants.util.strutil import help_text

# These fields are used by the `nfpm_deb_package` target
# Some fields will be duplicated by other package types which
# allows the help string to be packager-specific.


class NfpmDebMaintainerField(StringField):
    alias = "maintainer"
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
    alias = "section"
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
    alias = "priority"
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
