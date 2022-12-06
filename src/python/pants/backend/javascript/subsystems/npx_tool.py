# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ClassVar

from pants.option.option_types import StrOption
from pants.option.subsystem import Subsystem


class NpxToolBase(Subsystem):
    # Subclasses must set.
    default_version: ClassVar[str]

    version = StrOption(
        advanced=True,
        default=lambda cls: cls.default_version,
        help="Version string for the tool in the form package@version (e.g. prettier@2.6.2)",
    )
