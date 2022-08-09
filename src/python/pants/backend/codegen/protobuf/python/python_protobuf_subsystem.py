# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.codegen.protobuf.python.additional_fields import ProtobufPythonResolveField
from pants.backend.codegen.protobuf.target_types import (
    ProtobufDependenciesField,
    ProtobufGrpcToggleField,
)
from pants.backend.codegen.utils import find_python_runtime_library_or_raise_error
from pants.backend.python.dependency_inference.module_mapper import ThirdPartyPythonModuleMapping
from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url, git_url
from pants.util.strutil import softwrap


class PythonProtobufSubsystem(Subsystem):
    options_scope = "python-protobuf"
    help = softwrap(
        f"""
        Options related to the Protobuf Python backend.

        See {doc_url('protobuf-python')}.
        """
    )

    mypy_plugin = BoolOption(
        default=False,
        help=softwrap(
            """
            Use the `mypy-protobuf` plugin (https://github.com/dropbox/mypy-protobuf) to also
            generate .pyi type stubs.
            """
        ),
    )

    infer_runtime_dependency = BoolOption(
        default=True,
        help=softwrap(
            """
            If True, will add a dependency on a `python_requirement` target exposing the
            `protobuf` module (usually from the `protobuf` requirement). If the `protobuf_source`
            target sets `grpc=True`, will also add a dependency on the `python_requirement`
            target exposing the `grpcio` module.

            If `[python].enable_resolves` is set, Pants will only infer dependencies on
            `python_requirement` targets that use the same resolve as the particular
            `protobuf_source` / `protobuf_sources` target uses, which is set via its
            `python_resolve` field.

            Unless this option is disabled, Pants will error if no relevant target is found or
            if more than one is found which causes ambiguity.
            """
        ),
        advanced=True,
    )


class PythonProtobufMypyPlugin(PythonToolRequirementsBase):
    options_scope = "mypy-protobuf"
    help = "Configuration of the mypy-protobuf type stub generation plugin."

    default_version = "mypy-protobuf==2.10"

    # Since Pants doesn't plumb --constraints, use a requirement to constrain the
    # `Requires-Dist: protobuf (>=3.17.3)` requirement in mypy-protobuf 2.10 which now picks up
    # protobuf 4.x which is incompatible in practice.
    default_extra_requirements = ["protobuf<3.21"]

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.codegen.protobuf.python", "mypy_protobuf.lock")
    default_lockfile_path = "src/python/pants/backend/codegen/protobuf/python/mypy_protobuf.lock"
    default_lockfile_url = git_url(default_lockfile_path)


class MypyProtobufLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = PythonProtobufMypyPlugin.options_scope


@rule
def setup_mypy_protobuf_lockfile(
    _: MypyProtobufLockfileSentinel,
    mypy_protobuf: PythonProtobufMypyPlugin,
    python_setup: PythonSetup,
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(
        mypy_protobuf, use_pex=python_setup.generate_lockfiles_with_pex
    )


@dataclass(frozen=True)
class PythonProtobufDependenciesInferenceFieldSet(FieldSet):
    required_fields = (
        ProtobufDependenciesField,
        ProtobufPythonResolveField,
        ProtobufGrpcToggleField,
    )

    dependencies: ProtobufDependenciesField
    python_resolve: ProtobufPythonResolveField
    grpc_toggle: ProtobufGrpcToggleField


class InferPythonProtobufDependencies(InferDependenciesRequest):
    infer_from = PythonProtobufDependenciesInferenceFieldSet


@rule
async def infer_dependencies(
    request: InferPythonProtobufDependencies,
    python_protobuf: PythonProtobufSubsystem,
    python_setup: PythonSetup,
    # TODO(#12946): Make this a lazy Get once possible.
    module_mapping: ThirdPartyPythonModuleMapping,
) -> InferredDependencies:
    if not python_protobuf.infer_runtime_dependency:
        return InferredDependencies([])

    resolve = request.field_set.python_resolve.normalized_value(python_setup)

    result = [
        find_python_runtime_library_or_raise_error(
            module_mapping,
            request.field_set.address,
            "google.protobuf",
            resolve=resolve,
            resolves_enabled=python_setup.enable_resolves,
            recommended_requirement_name="protobuf",
            recommended_requirement_url="https://pypi.org/project/protobuf/",
            disable_inference_option=f"[{python_protobuf.options_scope}].infer_runtime_dependency",
        )
    ]

    if request.field_set.grpc_toggle.value:
        result.append(
            find_python_runtime_library_or_raise_error(
                module_mapping,
                request.field_set.address,
                # Note that the library is called `grpcio`, but the module is `grpc`.
                "grpc",
                resolve=resolve,
                resolves_enabled=python_setup.enable_resolves,
                recommended_requirement_name="grpcio",
                recommended_requirement_url="https://pypi.org/project/grpcio/",
                disable_inference_option=f"[{python_protobuf.options_scope}].infer_runtime_dependency",
            )
        )

    return InferredDependencies(result)


def rules():
    return [
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(InferDependenciesRequest, InferPythonProtobufDependencies),
        UnionRule(GenerateToolLockfileSentinel, MypyProtobufLockfileSentinel),
    ]
