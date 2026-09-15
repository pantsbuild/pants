# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections.abc import Mapping
from dataclasses import dataclass

from pants.backend.codegen.protobuf.buf.config import (
    LanguageGenTemplate,
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
from pants.option.option_types import BoolOption, DictOption, FileOption
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
    # No `pyi` plugins: the same target generates the stubs and the `_pb2.py`, so mapping
    # the `.py` is enough.
    # ConnectRPC.
    "remote:buf.build/connectrpc/python": "_connect",
    "local:protoc-gen-connect-python": "_connect",
    # gRPC (grpcio).
    "remote:buf.build/grpc/python": "_pb2_grpc",
    "local:protoc-gen-grpc-python": "_pb2_grpc",
    "local:protoc-gen-grpc_python": "_pb2_grpc",
    # gRPC (grpclib).
    "local:protoc-gen-grpclib_python": "_grpc",
    "local:protoc-gen-python_grpc": "_grpc",
}


class PythonProtobufSubsystem(Subsystem):
    options_scope = "python-protobuf"
    help = help_text(
        f"""
        Options related to the Protobuf Python backend.

        See {doc_url("docs/python/integrations/protobuf-and-grpc")}.
        """
    )

    buf_gen_template = FileOption(
        default=None,
        advanced=True,
        help=softwrap(
            """
            Path to the `buf.gen.yaml` template used to generate Python, when a
            `protobuf_source` opts into `protobuf_generator='buf'`.

            Takes precedence over `[buf].gen_template`. Set this when other languages
            generate from the same protos with plugins that need tooling this language's
            sandbox does not carry -- one `buf generate` run executes every plugin in its
            template, so those languages need templates of their own.

            Paths inside the template (`inputs:`, `out:`) are relative to the build root,
            because Pants runs `buf generate` from the sandbox root.
            """
        ),
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

    @property
    def language_gen_template(self) -> LanguageGenTemplate | None:
        return LanguageGenTemplate.from_option(self, "buf_gen_template")

    @property
    def buf_plugin_suffixes(self) -> dict[str, str]:
        """The built-in plugin suffixes, plus `extra_buf_plugin_suffixes`."""
        valid = sorted(set(DEFAULT_PLUGIN_SUFFIXES.values()))
        for plugin_id, suffix in self.extra_buf_plugin_suffixes.items():
            if suffix not in valid:
                raise ValueError(
                    f"`[{self.options_scope}].extra_buf_plugin_suffixes` has {suffix!r} for "
                    f"`{plugin_id}`. Expected one of: {', '.join(valid)}."
                )
        return {**DEFAULT_PLUGIN_SUFFIXES, **self.extra_buf_plugin_suffixes}


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
            language_template=python_protobuf.language_gen_template,
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
            # Unpinned plugins are fine here: only their ids are needed, and codegen enforces pins.
            suffix_outs = parse_plugin_outs(
                content,
                python_protobuf.buf_plugin_suffixes,
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
