# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import cast

from pants.backend.codegen.protobuf.target_types import ProtobufDependenciesField
from pants.backend.python.goals.lockfile import PythonLockfileRequest, PythonToolLockfileSentinel
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies
from pants.engine.unions import UnionRule
from pants.option.custom_types import target_option
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url, git_url


class PythonProtobufSubsystem(Subsystem):
    options_scope = "python-protobuf"
    help = f"Options related to the Protobuf Python backend.\n\nSee {doc_url('protobuf')}."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--runtime-dependencies",
            type=list,
            member_type=target_option,
            help=(
                "A list of addresses to `python_requirement` targets for the runtime "
                "dependencies needed for generated Python code to work. For example, "
                "`['3rdparty/python:protobuf', '3rdparty/python:grpcio']`. These dependencies will "
                "be automatically added to every `protobuf_sources` target"
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

    @property
    def runtime_dependencies(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self.options.runtime_dependencies, owning_address=None)

    @property
    def mypy_plugin(self) -> bool:
        return cast(bool, self.options.mypy_plugin)


class PythonProtobufMypyPlugin(PythonToolRequirementsBase):
    options_scope = "mypy-protobuf"
    help = "Configuration of the mypy-protobuf type stub generation plugin."

    default_version = "mypy-protobuf==2.4"

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.6"]

    register_lockfile = True
    default_lockfile_resource = (
        "pants.backend.codegen.protobuf.python",
        "mypy_protobuf_lockfile.txt",
    )
    default_lockfile_path = (
        "src/python/pants/backend/codegen/protobuf/python/mypy_protobuf_lockfile.txt"
    )
    default_lockfile_url = git_url(default_lockfile_path)


class MypyProtobufLockfileSentinel(PythonToolLockfileSentinel):
    options_scope = PythonProtobufMypyPlugin.options_scope


@rule
def setup_mypy_protobuf_lockfile(
    _: MypyProtobufLockfileSentinel, mypy_protobuf: PythonProtobufMypyPlugin
) -> PythonLockfileRequest:
    return PythonLockfileRequest.from_tool(mypy_protobuf)


class InjectPythonProtobufDependencies(InjectDependenciesRequest):
    inject_for = ProtobufDependenciesField


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
        UnionRule(PythonToolLockfileSentinel, MypyProtobufLockfileSentinel),
    ]
