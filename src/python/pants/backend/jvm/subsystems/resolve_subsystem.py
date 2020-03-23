# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.subsystem.subsystem import Subsystem

logger = logging.getLogger(__name__)


class JvmResolveSubsystem(Subsystem):
    """Used to keep track of global jvm resolver settings.

    :API: public
    """

    options_scope = "resolver"

    # TODO: Convert to an enum.
    CHOICES = ["coursier"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--resolver",
            choices=cls.CHOICES,
            default="coursier",
            help="Resolver to use for external jvm dependencies.",
        )
