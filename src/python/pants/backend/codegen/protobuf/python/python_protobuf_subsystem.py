# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import cast

from pants.backend.codegen.protobuf.target_types import ProtobufDependencies
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.base.deprecated import deprecated_conditional
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies
from pants.engine.unions import UnionRule
from pants.option.custom_types import target_option
from pants.option.ranked_value import Rank
from pants.option.subsystem import Subsystem
from pants.util.docutil import docs_url


class PythonProtobufSubsystem(Subsystem):
    options_scope = "python-protobuf"
    help = f"Options related to the Protobuf Python backend.\n\nSee {docs_url('protobuf')}."

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


class PythonProtobufMypyPlugin(PythonToolRequirementsBase):
    options_scope = PythonProtobufSubsystem.subscope("mypy-plugin")
    help = (
        "Configuration of the mypy-protobuf type stub generation plugin for the Protobuf Python "
        "backend."
    )

    default_version = "mypy-protobuf==2.4"
    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]

    def plugin_requirement(self, python_protobuf_subsystem: PythonProtobufSubsystem) -> str:
        deprecated_key = "mypy_plugin_version"
        mypy_plugin_requirement = python_protobuf_subsystem.options.get(deprecated_key)
        if mypy_plugin_requirement:
            # TODO(John Sirois): When removing this deprecation, its safe to remove the
            #  `--mypy-plugin-version` option registration in PythonProtobufSubsystem above since
            #  the `version` option registered by this subsystem is in a subscope picked to shadow
            #  the deprecated option in flag and environment variable namespaces; i.e.: both
            #  --python-protobuf-mypy-plugin-version and PANTS_PYTHON_PROTOBUF_MYPY_PLUGIN_VERSION
            #  will continue to work."
            deprecated_conditional(
                predicate=lambda: (
                    python_protobuf_subsystem.options.get_rank(deprecated_key) == Rank.CONFIG
                ),
                removal_version="2.5.0.dev0",
                entity_description=f"[{PythonProtobufSubsystem.options_scope}] {deprecated_key}",
                hint_message=(
                    f"Instead of configuring the `{deprecated_key}` in the "
                    f"`[{PythonProtobufSubsystem.options_scope}]` options section, configure the "
                    f"`version` in the `[{self.options_scope}]` options section."
                ),
            )
            return cast(str, mypy_plugin_requirement)
        return self.requirement


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
