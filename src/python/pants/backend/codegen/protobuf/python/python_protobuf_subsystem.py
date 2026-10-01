# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections.abc import Mapping
from dataclasses import dataclass

from pants.backend.codegen.protobuf.buf.config import (
    gen_template_request_from_fields,
    parse_plugin_outs,
)
from pants.backend.codegen.protobuf.buf.fields import BufGenTemplateField
from pants.backend.codegen.protobuf.buf.subsystem import BufSubsystem
from pants.backend.codegen.protobuf.python.additional_fields import ProtobufPythonResolveField
from pants.backend.codegen.protobuf.target_types import (
    ProtobufDependenciesField,
    ProtobufGeneratorField,
    ProtobufGrpcToggleField,
)
from pants.backend.codegen.utils import find_python_runtime_library_or_raise_error
from pants.backend.python.dependency_inference.module_mapper import (
    PythonModuleOwnersRequest,
    map_module_to_address,
)
from pants.backend.python.dependency_inference.subsystem import (
    AmbiguityResolution,
    PythonInferSubsystem,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.core.util_rules.config_files import find_config_file
from pants.engine.addresses import Address
from pants.engine.intrinsics import get_digest_contents
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption, DictOption
from pants.option.subsystem import Subsystem
from pants.source.source_root import SourceRootRequest, get_source_root
from pants.util.docutil import doc_url
from pants.util.strutil import help_text, softwrap

# pants: infer-dep(grpclib.lock*)
# pants: infer-dep(mypy_protobuf.lock*)


# Built-in registry mapping known buf plugin ids to the Python module-name suffix
# their output uses (e.g. `buf.build/grpc/python` produces `*_pb2_grpc.py`, so
# `_pb2_grpc` is the suffix). The Python `python_protobuf_module_mapper` consumes
# this to know which generated modules to register per proto file. Keys are
# `<kind>:<ident>`, where `<kind>` is `remote`, `protoc_builtin`, or `local` —
# matching the field name in `buf.gen.yaml` — so that identical names across
# kinds (e.g. a `local:` plugin named `python`) cannot collide. Users with
# custom plugin ids should layer additional entries via
# `[python-protobuf].extra_buf_plugin_suffixes`.
DEFAULT_PLUGIN_SUFFIXES: Mapping[str, str] = {
    # Core message codegen.
    "remote:buf.build/protocolbuffers/python": "_pb2",
    "protoc_builtin:python": "_pb2",
    "local:protoc-gen-python": "_pb2",
    # `.pyi` stubs share the same module name as `_pb2.py`, so map to the same suffix.
    "remote:buf.build/protocolbuffers/pyi": "_pb2",
    "protoc_builtin:pyi": "_pb2",
    # ConnectRPC.
    "remote:buf.build/connectrpc/python": "_connect",
    "local:protoc-gen-connect-python": "_connect",
    # gRPC (grpcio).
    "remote:buf.build/grpc/python": "_pb2_grpc",
    "local:protoc-gen-grpc-python": "_pb2_grpc",
    "local:protoc-gen-grpc_python": "_pb2_grpc",
    # gRPC (grpclib).
    "local:protoc-gen-grpclib_python": "_grpc",
}


# Built-in registry mapping known BSR module ids (declared in `buf.yaml`'s
# `deps:`) to the Python module names their generated `*_pb2.py` files produce
# when buf runs with `include_imports: true` on the `_pb2`-emitting plugin.
# The buf module mapper uses this to register dep-inference owners for imports
# of BSR-provided modules from hand-written user code. To refresh:
# `pants export-codegen ::` against a buf.yaml that lists the dep, then list
# the resulting `<out>/<…>_pb2.py` paths.
DEFAULT_BSR_DEP_MODULES: Mapping[str, tuple[str, ...]] = {
    "buf.build/bufbuild/protovalidate": (
        "buf.validate.expression_pb2",
        "buf.validate.validate_pb2",
    ),
    "buf.build/protocolbuffers/wellknowntypes": (
        "google.protobuf.any_pb2",
        "google.protobuf.api_pb2",
        "google.protobuf.descriptor_pb2",
        "google.protobuf.duration_pb2",
        "google.protobuf.empty_pb2",
        "google.protobuf.field_mask_pb2",
        "google.protobuf.source_context_pb2",
        "google.protobuf.struct_pb2",
        "google.protobuf.timestamp_pb2",
        "google.protobuf.type_pb2",
        "google.protobuf.wrappers_pb2",
    ),
    "buf.build/googleapis/googleapis": (
        "google.api.annotations_pb2",
        "google.api.field_behavior_pb2",
        "google.api.http_pb2",
        "google.rpc.code_pb2",
        "google.rpc.error_details_pb2",
        "google.rpc.status_pb2",
    ),
}


class PythonProtobufSubsystem(Subsystem):
    options_scope = "python-protobuf"
    help = help_text(
        f"""
        Options related to the Protobuf Python backend.

        See {doc_url("docs/python/integrations/protobuf-and-grpc")}.
        """
    )

    grpcio_plugin = BoolOption(
        default=True,
        help=softwrap(
            """
            Use the official `grpcio` plugin (https://pypi.org/project/grpcio/) to generate grpc
            service stubs.
            """
        ),
    )

    grpclib_plugin = BoolOption(
        default=False,
        help=softwrap(
            """
            Use the alternative `grpclib` plugin (https://github.com/vmagamedov/grpclib) to
            generate grpc service stubs.
            """
        ),
    )

    generate_type_stubs = BoolOption(
        default=False,
        mutually_exclusive_group="typestubs",
        help=softwrap(
            """
            If True, then configure `protoc` to also generate `.pyi` type stubs for each generated
            Python file. This option will work wih any recent version of `protoc` and should
            be preferred over the `--python-protobuf-mypy-plugin` option.
            """
        ),
    )

    mypy_plugin = BoolOption(
        default=False,
        mutually_exclusive_group="typestubs",
        help=softwrap(
            """
            Use the `mypy-protobuf` plugin (https://github.com/dropbox/mypy-protobuf) to also
            generate `.pyi` type stubs.

            Please prefer the `--python-protobuf-generate-type-stubs` option over this option
            since recent versions of `protoc` have the ability to directly generate type stubs.
            """
        ),
    )

    extra_buf_plugin_suffixes = DictOption[str](
        default={},
        help=softwrap(
            """
            Map of additional `buf.gen.yaml` plugin ids to the Python module-name
            suffix their output uses, layered on top of Pants's built-in registry
            of common plugins (e.g. `buf.build/protocolbuffers/python`,
            `buf.build/connectrpc/python`).

            Use this to teach Pants about custom or forked plugins. Keys are
            `<kind>:<id>`, where `<kind>` is `remote`, `protoc_builtin`, or
            `local` — matching the field name in the `buf.gen.yaml` plugin entry —
            and `<id>` is the plugin id exactly as it appears in that field
            (without any `:vX.Y` version suffix on `remote:` entries). Values are
            module-name suffixes from the set:

            - `_pb2` — produces message modules (`*_pb2.py`).
            - `_pb2_grpc` — produces grpcio service stubs (`*_pb2_grpc.py`).
            - `_grpc` — produces grpclib service stubs (`*_grpc.py`).
            - `_connect` — produces ConnectRPC service stubs (`*_connect.py`).

            Example:

                extra_buf_plugin_suffixes = {
                  "remote:myorg.example.com/internal/python-fork": "_pb2",
                  "remote:buf.build/example/some-grpc-fork": "_pb2_grpc",
                  "local:protoc-gen-myorg-python": "_pb2",
                }
            """
        ),
        advanced=True,
    )

    extra_buf_bsr_modules = DictOption[list[str]](
        default={},
        help=softwrap(
            """
            Map of BSR module ids (declared in `buf.yaml`'s `deps:`) to the
            Python module names their generated `*_pb2.py` files produce when
            buf runs with `include_imports: true`. Layered on top of Pants's
            built-in registry of common modules (e.g.
            `buf.build/bufbuild/protovalidate`,
            `buf.build/protocolbuffers/wellknowntypes`).

            Use this to teach Pants about BSR deps not in the built-in
            registry — typically internal company modules — so that
            hand-written code importing them doesn't trip "cannot infer
            owners" warnings.

            Example:

                extra_buf_bsr_modules = {
                  "buf.build/myorg/internal-types": [
                    "myorg.internal.types.foo_pb2",
                    "myorg.internal.types.bar_pb2",
                  ],
                }
            """
        ),
        advanced=True,
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
    help_short = "Configuration of the mypy-protobuf type stub generation plugin."

    default_requirements = ["mypy-protobuf>=3.4.0,<4"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.codegen.protobuf.python", "mypy_protobuf.lock")


class PythonProtobufGrpclibPlugin(PythonToolRequirementsBase):
    options_scope = "python-grpclib-protobuf"
    help_short = "Configuration of the grpclib plugin."

    default_requirements = ["grpclib[protobuf]>=0.4,<1"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.codegen.protobuf.python", "grpclib.lock")


@dataclass(frozen=True)
class PythonProtobufDependenciesInferenceFieldSet(FieldSet):
    required_fields = (
        ProtobufDependenciesField,
        ProtobufPythonResolveField,
        ProtobufGrpcToggleField,
        ProtobufGeneratorField,
        BufGenTemplateField,
    )

    dependencies: ProtobufDependenciesField
    python_resolve: ProtobufPythonResolveField
    grpc_toggle: ProtobufGrpcToggleField
    generator: ProtobufGeneratorField
    buf_gen_template: BufGenTemplateField


class InferPythonProtobufDependencies(InferDependenciesRequest):
    infer_from = PythonProtobufDependenciesInferenceFieldSet


# Mapping from generated-module suffix → (importable module, PyPI requirement
# name, requirement URL). Used by the buf branch of runtime-dep inference to add
# a runtime requirement on the right Python package when a plugin producing that
# suffix appears in `buf.gen.yaml`.
_BUF_RUNTIME_DEPS: tuple[tuple[str, str, str, str], ...] = (
    ("_pb2_grpc", "grpc", "grpcio", "https://pypi.org/project/grpcio/"),
    ("_grpc", "grpclib", "grpclib[protobuf]", "https://pypi.org/project/grpclib/"),
    ("_connect", "connectrpc", "connectrpc", "https://pypi.org/project/connectrpc/"),
)


async def _runtime_dep_for_module(
    *,
    module: str,
    field_set: PythonProtobufDependenciesInferenceFieldSet,
    python_setup: PythonSetup,
    locality: str | None,
    resolve: str,
    recommended_requirement_name: str,
    recommended_requirement_url: str,
    disable_inference_option: str,
) -> Address:
    addresses = await map_module_to_address(
        PythonModuleOwnersRequest(module, resolve=resolve, locality=locality),
        **implicitly(),
    )
    return find_python_runtime_library_or_raise_error(
        addresses,
        field_set.address,
        module,
        resolve=resolve,
        resolves_enabled=python_setup.enable_resolves,
        recommended_requirement_name=recommended_requirement_name,
        recommended_requirement_url=recommended_requirement_url,
        disable_inference_option=disable_inference_option,
    )


@rule
async def infer_dependencies(
    request: InferPythonProtobufDependencies,
    python_protobuf: PythonProtobufSubsystem,
    python_setup: PythonSetup,
    python_infer_subsystem: PythonInferSubsystem,
    buf: BufSubsystem,
) -> InferredDependencies:
    if not python_protobuf.infer_runtime_dependency:
        return InferredDependencies([])

    resolve = request.field_set.python_resolve.normalized_value(python_setup)

    locality = None
    if python_infer_subsystem.ambiguity_resolution == AmbiguityResolution.by_source_root:
        source_root = await get_source_root(
            SourceRootRequest.for_address(request.field_set.address)
        )
        locality = source_root.path

    disable_option = f"[{python_protobuf.options_scope}].infer_runtime_dependency"
    result = []
    result.append(
        await _runtime_dep_for_module(
            module="google.protobuf",
            field_set=request.field_set,
            python_setup=python_setup,
            locality=locality,
            resolve=resolve,
            recommended_requirement_name="protobuf",
            recommended_requirement_url="https://pypi.org/project/protobuf/",
            disable_inference_option=disable_option,
        )
    )

    if request.field_set.generator.value == "buf":
        # Buf path: generated-module suffixes come from `buf.gen.yaml`. Subsystem
        # booleans and `grpc=True` are not consulted.
        template_request = gen_template_request_from_fields(
            spec_path=request.field_set.address.spec_path,
            address_str=str(request.field_set.address),
            override=request.field_set.buf_gen_template.value,
            buf=buf,
        )
        template_files = await find_config_file(template_request)
        suffix_outs: dict[str, str] = {}
        if template_files.snapshot.files:
            template_path = template_files.snapshot.files[0]
            template_dcs = await get_digest_contents(template_files.snapshot.digest)
            content = next(
                (dc.content for dc in template_dcs if dc.path == template_path),
                b"",
            )
            # Don't enforce pinning here — codegen does. Inference reads the file
            # only to learn plugin ids → suffixes, which works regardless of pin state.
            suffix_outs = parse_plugin_outs(
                content,
                {**DEFAULT_PLUGIN_SUFFIXES, **python_protobuf.extra_buf_plugin_suffixes},
            )
        for suffix, module, req_name, req_url in _BUF_RUNTIME_DEPS:
            if suffix in suffix_outs:
                result.append(
                    await _runtime_dep_for_module(
                        module=module,
                        field_set=request.field_set,
                        python_setup=python_setup,
                        locality=locality,
                        resolve=resolve,
                        recommended_requirement_name=req_name,
                        recommended_requirement_url=req_url,
                        disable_inference_option=disable_option,
                    )
                )
        return InferredDependencies(result)

    # Protoc path: gated on `grpc=True` and the subsystem booleans, since Pants
    # drives the protoc invocation directly.
    if request.field_set.grpc_toggle.value:
        if python_protobuf.grpcio_plugin:
            result.append(
                await _runtime_dep_for_module(
                    # Note that the library is called `grpcio`, but the module is `grpc`.
                    module="grpc",
                    field_set=request.field_set,
                    python_setup=python_setup,
                    locality=locality,
                    resolve=resolve,
                    recommended_requirement_name="grpcio",
                    recommended_requirement_url="https://pypi.org/project/grpcio/",
                    disable_inference_option=disable_option,
                )
            )
        if python_protobuf.grpclib_plugin:
            result.append(
                await _runtime_dep_for_module(
                    module="grpclib",
                    field_set=request.field_set,
                    python_setup=python_setup,
                    locality=locality,
                    resolve=resolve,
                    recommended_requirement_name="grpclib[protobuf]",
                    recommended_requirement_url="https://pypi.org/project/grpclib/",
                    disable_inference_option=disable_option,
                )
            )

    return InferredDependencies(result)


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferPythonProtobufDependencies),
    ]
