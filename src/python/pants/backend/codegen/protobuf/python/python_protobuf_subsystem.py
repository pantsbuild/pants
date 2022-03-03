# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.codegen.protobuf.target_types import (
    ProtobufDependenciesField,
    ProtobufGrpcToggleField,
)
from pants.backend.codegen.utils import find_python_runtime_library_or_raise_error
from pants.backend.python.dependency_inference.module_mapper import ThirdPartyPythonModuleMapping
from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies, WrappedTarget
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
    ).deprecated(
        removal_version="2.11.0.dev0",
        hint=(
            "Pants can now infer dependencies on the Protobuf and gRPC runtime libraries for you. "
            "Not only is this more convenient, it allows Pants to support the new "
            "`[python].resolves` feature.\n\n"
            "To use Pants's new mechanism, simply remove this option. Run "
            "`./pants dependencies path/to/f.proto` to confirm that dependencies are still added "
            "correctly. You can disable this new dependency inference feature by setting "
            "`[python-protobuf].infer_runtime_dependency = false`."
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

    infer_runtime_dependency = BoolOption(
        "--infer-runtime-dependency",
        default=True,
        help=(
            "If True, will add a dependency on a `python_requirement` target exposing the "
            "`protobuf` module (usually from the `protobuf` requirement). If the `protobuf_source` "
            "target sets `grpc=True`, will also add a dependency on the `python_requirement` "
            "target exposing the `grpcio` module.\n\n"
            "If `[python].enable_resolves` is set, Pants will only infer dependencies on "
            "`python_requirement` targets that use the same resolve as the particular "
            "`protobuf_source` / `protobuf_sources` target uses, which is set via its "
            "`python_resolve` field.\n\n"
            "Unless this option is disabled, Pants will error if no relevant target is found or "
            "if more than one is found which causes ambiguity."
        ),
    ).advanced()

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
    request: InjectPythonProtobufDependencies,
    python_protobuf: PythonProtobufSubsystem,
    python_setup: PythonSetup,
    # TODO(#12946): Make this a lazy Get once possible.
    module_mapping: ThirdPartyPythonModuleMapping,
) -> InjectedDependencies:
    if python_protobuf.runtime_dependencies.values:
        addresses = await Get(
            Addresses, UnparsedAddressInputs, python_protobuf.runtime_dependencies
        )
        return InjectedDependencies(addresses)

    if not python_protobuf.infer_runtime_dependency:
        return InjectedDependencies()

    wrapped_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    tgt = wrapped_tgt.target
    resolve = tgt.get(PythonResolveField).normalized_value(python_setup)

    result = [
        find_python_runtime_library_or_raise_error(
            module_mapping,
            request.dependencies_field.address,
            "google.protobuf",
            resolve=resolve,
            resolves_enabled=python_setup.enable_resolves,
            recommended_requirement_name="protobuf",
            recommended_requirement_url="https://pypi.org/project/protobuf/",
            disable_inference_option=f"[{python_protobuf.options_scope}].infer_runtime_dependency",
        )
    ]

    if wrapped_tgt.target.get(ProtobufGrpcToggleField).value:
        result.append(
            find_python_runtime_library_or_raise_error(
                module_mapping,
                request.dependencies_field.address,
                # Note that the library is called `grpcio`, but the module is `grpc`.
                "grpc",
                resolve=resolve,
                resolves_enabled=python_setup.enable_resolves,
                recommended_requirement_name="grpcio",
                recommended_requirement_url="https://pypi.org/project/grpcio/",
                disable_inference_option=f"[{python_protobuf.options_scope}].infer_runtime_dependency",
            )
        )

    return InjectedDependencies(result)


def rules():
    return [
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(InjectDependenciesRequest, InjectPythonProtobufDependencies),
        UnionRule(GenerateToolLockfileSentinel, MypyProtobufLockfileSentinel),
    ]
