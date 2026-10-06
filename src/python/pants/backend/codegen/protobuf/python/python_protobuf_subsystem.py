# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pants.backend.codegen.protobuf.buf.config import (
    LanguageGenTemplate,
    gen_template_request_from_fields,
    parse_plugin_ids,
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


@dataclass(frozen=True)
class BufPythonPlugin:
    """What Pants needs to know about a buf plugin that generates Python."""

    # Appended to each `.proto` file's name to name its module, e.g. `_pb2` for `foo_pb2.py`.
    # `None` for a plugin whose modules aren't named that way; Pants doesn't map them.
    suffix: str | None
    # `(module, requirement)` for each module the generated code imports; the requirement is
    # suggested when no `python_requirement` provides the module.
    runtime: tuple[tuple[str, str], ...] = ()


_PB2 = BufPythonPlugin("_pb2", (("google.protobuf", "protobuf"),))
_GRPCIO = BufPythonPlugin("_pb2_grpc", (("grpc", "grpcio"),))
_GRPCLIB = BufPythonPlugin("_grpc", (("grpclib", "grpclib[protobuf]"),))
_CONNECT = BufPythonPlugin("_connect", (("connectrpc", "connectrpc"),))

# Keyed by `<kind>:<ident>`, where `<kind>` is the field in the `buf.gen.yaml` plugin entry
# (`remote`, `protoc_builtin` or `local`). No `pyi` plugins: the same target generates the
# stubs and the `_pb2.py`, so mapping the `.py` is enough.
DEFAULT_BUF_PYTHON_PLUGINS: Mapping[str, BufPythonPlugin] = {
    "remote:buf.build/protocolbuffers/python": _PB2,
    "protoc_builtin:python": _PB2,
    "local:protoc-gen-python": _PB2,
    "remote:buf.build/connectrpc/python": _CONNECT,
    "local:protoc-gen-connect-python": _CONNECT,
    "remote:buf.build/grpc/python": _GRPCIO,
    "local:protoc-gen-grpc-python": _GRPCIO,
    "local:protoc-gen-grpc_python": _GRPCIO,
    "local:protoc-gen-grpclib_python": _GRPCLIB,
    "local:protoc-gen-python_grpc": _GRPCLIB,
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

    extra_buf_plugins = DictOption[Any](
        default={},
        help=softwrap(
            """
            Additional buf plugins that generate Python, layered on top of Pants's built-in
            entries for common plugins (e.g. `buf.build/protocolbuffers/python`,
            `buf.build/grpc/python`).

            Keys are `<kind>:<id>`, where `<kind>` is the field in the `buf.gen.yaml` plugin
            entry (`remote`, `protoc_builtin` or `local`) and `<id>` is its value, without any
            `:<version>`. Each value has:

            - `suffix` (optional): what the plugin appends to each `.proto` file's name to name
              its module, e.g. `_pb2_grpc` for `foo_pb2_grpc.py`, so Pants can infer
              dependencies on the generated modules. Leave it out for a plugin whose modules
              are named some other way.
            - `runtime` (optional): modules the generated code imports, so Pants can add
              dependencies on the requirements that provide them.

            Example:

                extra_buf_plugins = {
                  "local:protoc-gen-myorg-python": {"suffix": "_pb2", "runtime": ["google.protobuf"]},
                  "remote:buf.build/example/grpc-fork": {"suffix": "_pb2_grpc", "runtime": ["grpc"]},
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
    def buf_plugins(self) -> dict[str, BufPythonPlugin]:
        """The built-in buf plugins, plus `extra_buf_plugins`."""
        plugins = dict(DEFAULT_BUF_PYTHON_PLUGINS)
        for plugin_id, entry in self.extra_buf_plugins.items():
            suffix = entry.get("suffix") if isinstance(entry, dict) else None
            runtime = entry.get("runtime", []) if isinstance(entry, dict) else None
            if (
                not isinstance(entry, dict)
                or (suffix is not None and (not isinstance(suffix, str) or not suffix))
                or not isinstance(runtime, list)
                or not all(isinstance(m, str) for m in runtime)
                or set(entry) - {"suffix", "runtime"}
            ):
                raise ValueError(
                    f"`[{self.options_scope}].extra_buf_plugins` has {entry!r} for "
                    f'`{plugin_id}`. Expected `{{"suffix": <str>, "runtime": [<module>, ...]}}`, '
                    "with both optional."
                )
            plugins[plugin_id] = BufPythonPlugin(suffix, tuple((m, m) for m in runtime))
        return plugins


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

    if request.field_set.generator.value == "buf":
        # Buf path: each runtime comes from a plugin in the template. Subsystem booleans and
        # `grpc=True` are not consulted.
        template_request = gen_template_request_from_fields(
            spec_path=request.field_set.address.spec_path,
            address_str=str(request.field_set.address),
            override=request.field_set.buf_gen_template.value,
            buf=buf,
            language_template=python_protobuf.language_gen_template,
        )
        template_files = await find_config_file(template_request)
        runtime: dict[str, str] = {}
        if template_files.snapshot.files:
            template_path = template_files.snapshot.files[0]
            template_dcs = await get_digest_contents(template_files.snapshot.digest)
            content = next(
                (dc.content for dc in template_dcs if dc.path == template_path),
                b"",
            )
            plugins = python_protobuf.buf_plugins
            # Unpinned plugins are fine here: only their ids are needed, and codegen enforces pins.
            for plugin_id in parse_plugin_ids(content):
                if plugin_id in plugins:
                    runtime.update(plugins[plugin_id].runtime)
        for module, requirement in runtime.items():
            result.append(
                await _runtime_dep_for_module(
                    module=module,
                    field_set=request.field_set,
                    python_setup=python_setup,
                    locality=locality,
                    resolve=resolve,
                    recommended_requirement_name=requirement,
                    recommended_requirement_url=(
                        f"https://pypi.org/project/{requirement.split('[')[0]}/"
                    ),
                    disable_inference_option=disable_option,
                )
            )
        return InferredDependencies(result)

    # Protoc path: gated on `grpc=True` and the subsystem booleans, since Pants
    # drives the protoc invocation directly.
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
