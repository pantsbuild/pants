# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.codegen.protobuf.target_types import ProtobufDependenciesField
from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption, TargetListOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url, git_url


class PythonProtobufSubsystem(Subsystem):
    options_scope = "python-protobuf"
    help = f"Options related to the Protobuf Python backend.\n\nSee {doc_url('protobuf')}."

    _runtime_dependencies = TargetListOption(
        "--runtime-dependencies",
        help=(
            "A list of addresses to `python_requirement` targets for the runtime "
            "dependencies needed for generated Python code to work. For example, "
            "`['3rdparty/python:protobuf', '3rdparty/python:grpcio']`. These dependencies will "
            "be automatically added to every `protobuf_sources` target"
        ),
    )

    mypy_plugin = BoolOption(
        "--mypy-plugin",
        default=False,
        help=(
            "Use the `mypy-protobuf` plugin (https://github.com/dropbox/mypy-protobuf) to "
            "also generate .pyi type stubs."
        ),
    )

    @property
    def runtime_dependencies(self) -> UnparsedAddressInputs:
        return UnparsedAddressInputs(self._runtime_dependencies, owning_address=None)


class PythonProtobufMypyPlugin(PythonToolRequirementsBase):
    options_scope = "mypy-protobuf"
    help = "Configuration of the mypy-protobuf type stub generation plugin."

    default_version = "mypy-protobuf==2.10"

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


class MypyProtobufLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = PythonProtobufMypyPlugin.options_scope


@rule
def setup_mypy_protobuf_lockfile(
    _: MypyProtobufLockfileSentinel, mypy_protobuf: PythonProtobufMypyPlugin
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(mypy_protobuf)


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
        *lockfile.rules(),
        UnionRule(InjectDependenciesRequest, InjectPythonProtobufDependencies),
        UnionRule(GenerateToolLockfileSentinel, MypyProtobufLockfileSentinel),
    ]
