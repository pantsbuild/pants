# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.subsystem.subsystem import Subsystem
from pants.engine.rules import SubsystemRule


class Options(Subsystem):
    options_scope = "mock-options"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--crufty-deprecated-but-still-functioning",
            removal_version="999.99.9.dev0",
            removal_hint="blah",
        )
        register("--normal-option")


def rules():
    return [SubsystemRule(Options)]
