# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import DefaultDict

from pants.backend.codegen.protobuf.buf.config import (
    BufGenContent,
    BufLayout,
    fetch_buf_gen_contents,
    fetch_buf_layout,
    parse_plugin_outs,
    suffix_plugin_includes_imports,
)
from pants.backend.codegen.protobuf.buf.subsystem import BufSubsystem
from pants.backend.codegen.protobuf.python.additional_fields import PythonSourceRootField
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    DEFAULT_BSR_DEP_MODULES,
    DEFAULT_PLUGIN_SUFFIXES,
    PythonProtobufSubsystem,
)
from pants.backend.codegen.protobuf.target_types import (
    AllProtobufTargets,
    ProtobufGeneratorField,
    ProtobufGrpcToggleField,
    ProtobufSourceField,
)
from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonMappingImpl,
    FirstPartyPythonMappingImplMarker,
    ModuleProvider,
    ModuleProviderType,
    ResolveName,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
from pants.core.util_rules.stripped_source_files import StrippedFileNameRequest, strip_file_name
from pants.engine.rules import collect_rules, concurrently, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


def proto_path_to_py_module(stripped_path: str, *, suffix: str) -> str:
    return stripped_path.replace(".proto", suffix).replace("/", ".")


# This is only used to register our implementation with the plugin hook via unions.
class PythonProtobufMappingMarker(FirstPartyPythonMappingImplMarker):
    pass


# Suffixes relevant to Python codegen. Each is registered iff its plugin appears
# in `buf.gen.yaml`.
_PB2_SUFFIX = "_pb2"
_SERVICE_SUFFIXES: tuple[str, ...] = ("_pb2_grpc", "_grpc", "_connect")


@dataclass(frozen=True)
class _BufStripPlan:
    """Plan for one buf target: paths to feed to `strip_file_name`, paired with the
    suffix to apply to each stripped result."""

    suffixes: tuple[str, ...]
    paths_to_strip: tuple[str, ...]


def _plan_buf_target(
    target: Target,
    suffix_outs: Mapping[str, str],
    buf_module_root: str,
) -> _BufStripPlan:
    """Build the strip plan from the suffixes matched in this target's `buf.gen.yaml`.

    A suffix is registered iff its plugin appears in the file. `grpc=True` is
    *not* consulted: `buf.gen.yaml` is the authoritative source of truth for
    which buf target outputs exist.
    """
    proto_path = target[ProtobufSourceField].file_path
    rel_proto = (
        os.path.relpath(proto_path, buf_module_root)
        if buf_module_root
        and (proto_path == buf_module_root or proto_path.startswith(buf_module_root + os.sep))
        else proto_path
    )

    def _path_for(out_dir: str) -> str:
        return os.path.normpath(os.path.join(out_dir, rel_proto))

    suffixes: list[str] = []
    paths: list[str] = []
    if _PB2_SUFFIX in suffix_outs:
        suffixes.append(_PB2_SUFFIX)
        paths.append(_path_for(suffix_outs[_PB2_SUFFIX]))
    for suffix in _SERVICE_SUFFIXES:
        if suffix in suffix_outs:
            suffixes.append(suffix)
            paths.append(_path_for(suffix_outs[suffix]))

    return _BufStripPlan(tuple(suffixes), tuple(paths))


def _fallback_plan(target: Target) -> _BufStripPlan:
    """Plan when no `buf.gen.yaml` was found: assume the proto's source root also
    covers the generated `.py`. Service suffixes can't be inferred without the
    template, so we register only `_pb2`."""
    proto_path = target[ProtobufSourceField].file_path
    return _BufStripPlan((_PB2_SUFFIX,), (proto_path,))


# Protoc-only subsystem options. Their default values are mirrored here so we can
# detect when the user explicitly set them while also using buf targets, and warn
# that they're ignored on the buf path. Keep in sync with the option definitions
# in `python_protobuf_subsystem.py`.
_PROTOC_ONLY_OPTION_DEFAULTS: tuple[tuple[str, object], ...] = (
    ("grpcio_plugin", True),
    ("grpclib_plugin", False),
    ("mypy_plugin", False),
    ("generate_type_stubs", False),
)


def _emit_subsystem_warnings_for_buf(subsystem: PythonProtobufSubsystem) -> None:
    """Warn once if subsystem options that are protoc-only are set non-default
    while at least one buf target exists."""
    for option_name, default in _PROTOC_ONLY_OPTION_DEFAULTS:
        if getattr(subsystem, option_name) == default:
            continue
        logger.warning(
            "[%s].%s is set but ignored for `protobuf_generator='buf'` targets. "
            "Service generation and `.pyi` stubs for buf targets are determined by "
            "the plugin entries in `buf.gen.yaml`.",
            subsystem.options_scope,
            option_name,
        )


def _emit_per_target_warnings_for_buf(target: Target) -> None:
    """Warn once per buf target about field values that have no effect."""
    if target.get(ProtobufGrpcToggleField).value:
        logger.warning(
            "`grpc=True` is set on %s but is ignored for `protobuf_generator='buf'` "
            "targets. Whether `_pb2_grpc.py` / `_grpc.py` / `_connect.py` exist is "
            "determined by the plugins in `buf.gen.yaml`.",
            target.address,
        )
    if target.get(PythonSourceRootField).value is not None:
        logger.warning(
            "`python_source_root` is set on %s but ignored for "
            "`protobuf_generator='buf'`; output paths come from the `out:` field of "
            "`buf.gen.yaml`.",
            target.address,
        )


@rule(desc="Creating map of Protobuf targets to generated Python modules", level=LogLevel.DEBUG)
async def map_protobuf_to_python_modules(
    protobuf_targets: AllProtobufTargets,
    python_setup: PythonSetup,
    python_protobuf_subsystem: PythonProtobufSubsystem,
    buf: BufSubsystem,
    _: PythonProtobufMappingMarker,
) -> FirstPartyPythonMappingImpl:
    grpc_suffixes_list: list[str] = []
    if python_protobuf_subsystem.grpcio_plugin:
        grpc_suffixes_list.append("_pb2_grpc")
    if python_protobuf_subsystem.grpclib_plugin:
        grpc_suffixes_list.append("_grpc")
    grpc_suffixes = tuple(grpc_suffixes_list)

    protoc_targets: list[Target] = []
    buf_targets: list[Target] = []
    for tgt in protobuf_targets:
        if tgt.get(ProtobufGeneratorField).value == "buf":
            buf_targets.append(tgt)
        else:
            protoc_targets.append(tgt)

    if buf_targets:
        _emit_subsystem_warnings_for_buf(python_protobuf_subsystem)

    # ---- protoc path. ----
    stripped_file_per_protoc_target = await concurrently(
        strip_file_name(StrippedFileNameRequest(tgt[ProtobufSourceField].file_path))
        for tgt in protoc_targets
    )

    # ---- buf path: registry-driven plugin matching, no `grpc=True` gate. ----
    if buf_targets:
        buf_layout: BufLayout = await fetch_buf_layout(buf)
        buf_gen_contents: tuple[BufGenContent, ...] = await fetch_buf_gen_contents(buf_targets, buf)
    else:
        buf_layout = BufLayout("", (), ())
        buf_gen_contents = ()

    plugin_suffixes = {
        **DEFAULT_PLUGIN_SUFFIXES,
        **python_protobuf_subsystem.extra_buf_plugin_suffixes,
    }
    plans: list[_BufStripPlan] = []
    for gen in buf_gen_contents:
        _emit_per_target_warnings_for_buf(gen.target)
        if gen.template_path is None:
            logger.debug(
                "No `buf.gen.yaml` resolved for %s; falling back to source-root path "
                "arithmetic for `_pb2` only. Service suffixes can't be inferred without "
                "the template.",
                gen.target.address,
            )
            plans.append(_fallback_plan(gen.target))
            continue
        # Inference doesn't enforce pinning — that's codegen's job. Inference
        # works fine on unpinned entries (we only need plugin ids to look up
        # suffixes), so the user's editor-side dep inference doesn't fail on
        # in-flight `buf.gen.yaml` edits.
        suffix_outs = parse_plugin_outs(gen.content, plugin_suffixes)
        proto_path = gen.target[ProtobufSourceField].file_path
        buf_module_root = buf_layout.root_for_proto(proto_path)
        plans.append(_plan_buf_target(gen.target, suffix_outs, buf_module_root))

    flat_strip_requests: list[StrippedFileNameRequest] = [
        StrippedFileNameRequest(p) for plan in plans for p in plan.paths_to_strip
    ]
    flat_stripped = (
        await concurrently(strip_file_name(req) for req in flat_strip_requests)
        if flat_strip_requests
        else ()
    )

    # Reassemble per-target module lists.
    buf_modules_per_target: list[list[str]] = []
    idx = 0
    for plan in plans:
        target_modules: list[str] = []
        for suffix in plan.suffixes:
            stripped = flat_stripped[idx]
            target_modules.append(proto_path_to_py_module(stripped.value, suffix=suffix))
            idx += 1
        buf_modules_per_target.append(target_modules)

    # ---- Build the module → providers map. ----
    resolves_to_modules_to_providers: DefaultDict[
        ResolveName, DefaultDict[str, list[ModuleProvider]]
    ] = defaultdict(lambda: defaultdict(list))

    for tgt, stripped_file in zip(protoc_targets, stripped_file_per_protoc_target):
        resolve = tgt[PythonResolveField].normalized_value(python_setup)

        # NB: We don't consider the MyPy plugin, which generates `_pb2.pyi`. The stubs end up
        # sharing the same module as the implementation `_pb2.py`. Because both generated files
        # come from the same original Protobuf target, we're covered.
        module = proto_path_to_py_module(stripped_file.value, suffix="_pb2")
        resolves_to_modules_to_providers[resolve][module].append(
            ModuleProvider(tgt.address, ModuleProviderType.IMPL)
        )
        if tgt.get(ProtobufGrpcToggleField).value:
            for suffix in grpc_suffixes:
                module = proto_path_to_py_module(stripped_file.value, suffix=suffix)
                resolves_to_modules_to_providers[resolve][module].append(
                    ModuleProvider(tgt.address, ModuleProviderType.IMPL)
                )

    for tgt, modules in zip(buf_targets, buf_modules_per_target):
        resolve = tgt[PythonResolveField].normalized_value(python_setup)
        for module in modules:
            resolves_to_modules_to_providers[resolve][module].append(
                ModuleProvider(tgt.address, ModuleProviderType.IMPL)
            )

    # Register BSR-dep Python modules as owned by buf targets that actually
    # generate them. A target only generates BSR-dep `*_pb2.py` files if its
    # `buf.gen.yaml` has `include_imports: true` on whichever plugin emits
    # `_pb2` (the BSR remote, `protoc_builtin: python`, etc.) — otherwise the
    # file isn't in the `GeneratedSources` digest and registering ownership
    # would lie. Targets without `include_imports` are skipped; users either set
    # it or accept the dep-inference warning.
    if buf_layout.deps and buf_targets:
        bsr_to_modules: Mapping[str, Sequence[str]] = {
            **{k: tuple(v) for k, v in DEFAULT_BSR_DEP_MODULES.items()},
            **{k: tuple(v) for k, v in python_protobuf_subsystem.extra_buf_bsr_modules.items()},
        }
        bsr_modules_for_layout: list[str] = []
        for dep in buf_layout.deps:
            bsr_modules_for_layout.extend(bsr_to_modules.get(dep, ()))
        for tgt, gen in zip(buf_targets, buf_gen_contents):
            if not suffix_plugin_includes_imports(gen.content, "_pb2", plugin_suffixes):
                continue
            resolve = tgt[PythonResolveField].normalized_value(python_setup)
            for module in bsr_modules_for_layout:
                resolves_to_modules_to_providers[resolve][module].append(
                    ModuleProvider(tgt.address, ModuleProviderType.IMPL)
                )

    return FirstPartyPythonMappingImpl.create(resolves_to_modules_to_providers)


def rules():
    return (
        *collect_rules(),
        UnionRule(FirstPartyPythonMappingImplMarker, PythonProtobufMappingMarker),
    )
