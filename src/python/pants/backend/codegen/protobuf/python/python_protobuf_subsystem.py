# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import cast

from pants.backend.codegen.protobuf.target_types import ProtobufDependencies
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies
from pants.engine.unions import UnionRule
from pants.option.custom_types import target_option
from pants.option.subsystem import Subsystem


class PythonProtobufSubsystem(Subsystem):
    """Options related to the Protobuf Python backend.

    See https://www.pantsbuild.org/docs/protobuf.
    """

    options_scope = "python-protobuf"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--runtime-dependencies",
            type=list,
            member_type=target_option,
            help=(
                "A list of addresses to `python_requirement_library` targets for the runtime "
                "dependencies needed for generated Python code to work. For example, "
                "`['3rdparty/python:protobuf', '3rdparty/python:grpcio']`. These dependencies will "
                "be automatically added to every `protobuf_library` target"
            ),
        )
        register(
            "--mypy-plugin",
            type=bool,
            default=False,
            help=(
                "Use the `mypy-protobuf` plugin (https://github.com/dropbox/mypy-protobuf) to "
                "also generate .pyi type stubs."
            ),
        )
        register(
            "--mypy-plugin-version",
            type=str,
            default="mypy-protobuf==1.23",
            advanced=True,
            help=(
                "The pip-style requirement string for `mypy-protobuf`. You must still set "
                "`--mypy-plugin` for this option to be used."
            ),
        )

    @property
    def runtime_dependencies(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self.options.runtime_dependencies, owning_address=None)

    @property
    def mypy_plugin(self) -> bool:
        return cast(bool, self.options.mypy_plugin)

    @property
    def mypy_plugin_version(self) -> str:
        return cast(str, self.options.mypy_plugin_version)


class InjectPythonProtobufDependencies(InjectDependenciesRequest):
    inject_for = ProtobufDependencies


@rule
async def inject_dependencies(
    _: InjectPythonProtobufDependencies, python_protobuf: PythonProtobufSubsystem
) -> InjectedDependencies:
    addresses = await Get(Addresses, UnparsedAddressInputs, python_protobuf.runtime_dependencies)
    return InjectedDependencies(addresses)


def rules():
    return [
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectPythonProtobufDependencies),
    ]
