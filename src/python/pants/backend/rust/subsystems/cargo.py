# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.rules import SubsystemRule, rule
from pants.subsystem.subsystem import Subsystem


@dataclass(frozen=True)
class Cargo:
    version: str

    class Factory(Subsystem):
        options_scope = 'cargo-toolchain'

        @classmethod
        def register_options(cls, register):
            super().register_options(register)
            # TODO: is there a 'stable' version for cargo, like the rust toolchain?
            register('--version', type=str, default='0.43.0', metavar='<version>',
                     help='The version of cargo to use.')


@rule
def get_cargo(cargo_factory: Cargo.Factory) -> Cargo:
    version = cargo_factory.get_options().version
    return Cargo(version)


def rules():
    return [
        SubsystemRule(Cargo.Factory),
        get_cargo,
    ]
