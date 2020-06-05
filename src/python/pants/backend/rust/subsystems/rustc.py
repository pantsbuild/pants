# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.rules import SubsystemRule, rule
from pants.subsystem.subsystem import Subsystem


@dataclass(frozen=True)
class Rustc:
    version: str

    class Factory(Subsystem):
        options_scope = 'rustc'

        @classmethod
        def register_options(cls, register):
            super().register_options(register)
            register('--version', type=str, default='stable', metavar='<version>',
                     help='The version of rustc to use.')



@rule
def get_rustc(rustc_factory: Rustc.Factory) -> Rustc:
    version = rustc_factory.get_options().version
    return Rustc(version)


def rules():
    return [
        SubsystemRule(Rustc.Factory),
        get_rustc,
    ]
