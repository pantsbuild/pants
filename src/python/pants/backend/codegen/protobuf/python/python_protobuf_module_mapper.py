# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import DefaultDict

from pants.backend.codegen.protobuf.buf.config import (
    BufGenContent,
    BufLayout,
    fetch_buf_gen_contents,
    fetch_buf_layout,
    parse_plugin_outs,
)
from pants.backend.codegen.protobuf.buf.subsystem import BufSubsystem
from pants.backend.codegen.protobuf.python.additional_fields import PythonSourceRootField
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
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
from pants.core.util_rules import config_files
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

    A suffix is registered only if its plugin appears in the template; `grpc=True` isn't
    consulted.
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

    return _BufStripPlan(tuple(suffix_outs), tuple(_path_for(out) for out in suffix_outs.values()))


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
    """Warn about this target's fields that have no effect with buf."""
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

    # ---- buf path: plugins and `out:` come from each target's template. ----
    if buf_targets:
        buf_layout: BufLayout = await fetch_buf_layout(buf)
        buf_gen_contents: tuple[BufGenContent, ...] = await fetch_buf_gen_contents(
            buf_targets,
            buf,
            python_protobuf_subsystem.language_gen_template,
        )
    else:
        buf_layout = BufLayout("", ())
        buf_gen_contents = ()

    plugin_suffixes = {
        plugin_id: plugin.suffix
        for plugin_id, plugin in python_protobuf_subsystem.buf_plugins.items()
        if plugin.suffix
    }
    plans: list[_BufStripPlan] = []
    for gen in buf_gen_contents:
        _emit_per_target_warnings_for_buf(gen.target)
        if gen.template_path is None:
            # Without a template, codegen fails and generates nothing.
            plans.append(_BufStripPlan((), ()))
            continue
        # Unpinned plugins are fine here: only their ids are needed, and codegen enforces pins.
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

    return FirstPartyPythonMappingImpl.create(resolves_to_modules_to_providers)


def rules():
    return (
        *collect_rules(),
        *config_files.rules(),
        UnionRule(FirstPartyPythonMappingImplMarker, PythonProtobufMappingMarker),
    )
