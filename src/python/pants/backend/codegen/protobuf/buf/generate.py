# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass

from pants.backend.codegen.protobuf.buf import fields as buf_fields
from pants.backend.codegen.protobuf.buf import lockfile as buf_lockfile
from pants.backend.codegen.protobuf.buf.config import (
    BufLayout,
    LanguageGenTemplate,
    MissingBufLockError,
    buf_resolve_name,
    fetch_buf_layout,
    find_buf_config_files,
    gen_template_request_for_target,
    resolved_template_path,
    synthesize_pinned_buf_gen_yaml,
)
from pants.backend.codegen.protobuf.buf.subsystem import BufSubsystem
from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.target_types import ProtobufSourceField
from pants.core.util_rules.adhoc_process_support import (
    ExtraSandboxContents,
    MergeExtraSandboxContents,
    ResolveRunnableDependenciesRequest,
    merge_extra_sandbox_contents,
    resolve_runnable_dependencies,
)
from pants.core.util_rules.adhoc_process_support import rules as adhoc_process_support_rules
from pants.core.util_rules.config_files import ConfigFiles, find_config_file
from pants.core.util_rules.external_tool import download_external_tool
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    Directory,
    FileContent,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.graph import transitive_targets as transitive_targets_get
from pants.engine.intrinsics import (
    create_digest,
    digest_to_snapshot,
    get_digest_contents,
    merge_digests,
    remove_prefix,
)
from pants.engine.platform import Platform
from pants.engine.process import Process, execute_process_or_raise
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import Target, TransitiveTargetsRequest
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class BufGenerateRequest:
    """Run `buf generate` for one target's protos.

    `toolchain` is anything else the language's plugins need in the sandbox, e.g. a Node.js
    package for TypeScript.
    """

    target: Target
    language_template: LanguageGenTemplate | None
    description: str
    toolchain: ExtraSandboxContents | None = None


@dataclass(frozen=True)
class BufGenerateResult:
    snapshot: Snapshot


def _check_buf_lock(layout: BufLayout) -> None:
    # A `buf.lock` pins each BSR dep to an exact commit; without one, buf resolves `deps:` to
    # whatever is currently latest on the BSR.
    if not layout.deps or layout.has_lock or layout.buf_yaml_path is None:
        return
    raise MissingBufLockError(
        f"`{layout.buf_yaml_path}` declares `deps:` ({', '.join(layout.deps)}) but no "
        f"`{os.path.join(layout.buf_yaml_dir, 'buf.lock')}` was found. Pants requires a "
        "`buf.lock` so BSR deps are pinned and codegen is reproducible.\n\n"
        f"Run `pants generate-lockfiles --resolve={buf_resolve_name(layout.buf_yaml_path)}` "
        "to create it."
    )


async def _pin_gen_template(gen_template_files: ConfigFiles, buf: BufSubsystem) -> Digest:
    # Resolve every `remote:` plugin to an exact `:vX.Y:revN` pin before
    # invoking buf. Unpinned entries that can be filled in from
    # `DEFAULT_PLUGIN_PINS` (or the user's `[buf].extra_plugin_pins`) get a
    # default; unknown unpinned entries raise. The resulting yaml is written
    # into a fresh digest that replaces the user's `buf.gen.yaml` in the
    # sandbox, so buf sees a hermetic, fully-pinned config.
    gen_template_digest = gen_template_files.snapshot.digest
    if not gen_template_files.snapshot.files:
        return gen_template_digest
    gen_template_path = gen_template_files.snapshot.files[0]
    gen_template_dcs = await get_digest_contents(gen_template_digest)
    gen_template_content = next(
        (dc.content for dc in gen_template_dcs if dc.path == gen_template_path),
        b"",
    )
    synthesized = synthesize_pinned_buf_gen_yaml(
        gen_template_content,
        gen_template_path,
        extra_pins=buf.extra_plugin_pins,
    )
    if synthesized == gen_template_content:
        return gen_template_digest
    return await create_digest(CreateDigest([FileContent(gen_template_path, synthesized)]))


@rule(desc="Generate code from Protobuf via `buf generate`", level=LogLevel.DEBUG)
async def run_buf_generate(
    request: BufGenerateRequest, buf: BufSubsystem, protoc: Protoc, platform: Platform
) -> BufGenerateResult:
    target = request.target
    output_dir = "_generated_files"

    # Buf needs all transitive `.proto` sources to resolve imports, even though only
    # the target's own files are passed via `--path`.
    transitive_targets = await transitive_targets_get(
        TransitiveTargetsRequest([target.address]), **implicitly()
    )

    (
        downloaded_buf,
        downloaded_protoc,
        empty_output_dir,
        all_sources,
        target_sources,
        codegen_plugins,
        config_files,
        gen_template_files,
    ) = await concurrently(
        download_external_tool(buf.get_request(platform)),
        download_external_tool(protoc.get_request(platform)),
        create_digest(CreateDigest([Directory(output_dir)])),
        # Unlike the protoc path, buf operates on original (unstripped) paths because
        # the buf module root is determined by `buf.yaml`'s location, not by Pants source
        # roots.
        determine_source_files(
            SourceFilesRequest(
                tgt[ProtobufSourceField]
                for tgt in transitive_targets.closure
                if tgt.has_field(ProtobufSourceField)
            )
        ),
        determine_source_files(SourceFilesRequest([target[ProtobufSourceField]])),
        resolve_runnable_dependencies(
            ResolveRunnableDependenciesRequest(
                UnparsedAddressInputs(
                    buf.codegen_plugins,
                    owning_address=None,
                    description_of_origin=(
                        f"the `[{BufSubsystem.options_scope}].codegen_plugins` option"
                    ),
                )
            ),
            **implicitly(),
        ),
        find_buf_config_files(buf),
        find_config_file(gen_template_request_for_target(target, buf, request.language_template)),
    )

    _check_buf_lock(await fetch_buf_layout(buf))
    gen_template_digest = await _pin_gen_template(gen_template_files, buf)

    # Put `protoc` (and any plugin binaries co-located with it) on PATH so buf can resolve
    # `protoc_builtin:` and `local: [protoc]` entries, and `[buf].codegen_plugins` so it can
    # resolve `local: <name>`.
    protoc_relpath = "__protoc"
    sandbox_additions = [
        ExtraSandboxContents(
            digest=EMPTY_DIGEST,
            paths=(os.path.join(protoc_relpath, os.path.dirname(downloaded_protoc.exe)),),
            immutable_input_digests=FrozenDict({protoc_relpath: downloaded_protoc.digest}),
            append_only_caches=FrozenDict(),
            extra_env=FrozenDict(),
        )
    ]
    if request.toolchain:
        sandbox_additions.append(request.toolchain)
    plugins = codegen_plugins.runnable_dependencies
    if plugins:
        sandbox_additions.append(
            ExtraSandboxContents(
                digest=codegen_plugins.digest,
                paths=(f"{{chroot}}/{plugins.path_component}",),
                immutable_input_digests=plugins.immutable_input_digests,
                append_only_caches=plugins.append_only_caches,
                extra_env=plugins.extra_env,
            )
        )
    sandbox = await merge_extra_sandbox_contents(
        MergeExtraSandboxContents(tuple(sandbox_additions))
    )

    input_digest = await merge_digests(
        MergeDigests(
            (
                all_sources.snapshot.digest,
                sandbox.digest,
                empty_output_dir,
                downloaded_buf.digest,
                config_files.snapshot.digest,
                gen_template_digest,
            )
        )
    )

    config_arg = ["--config", buf.config] if buf.config else []
    template_path = resolved_template_path(target, buf, request.language_template)
    template_arg = ["--template", template_path] if template_path else []

    # Read the same switch that shapes the sandbox so the two can't disagree.
    # Inference on: the sandbox holds only this target's declared imports, so
    # `--path` scopes generation to its files. Inference off: every sandbox holds
    # the full proto tree, so we drop `--path` and let each invocation emit the
    # whole package — identical bytes that `MergeDigests` can dedupe (e.g.
    # betterproto2's one `__init__.py` per package).
    path_arg = (
        ["--path", ",".join(target_sources.snapshot.files)] if protoc.dependency_inference else []
    )

    result = await execute_process_or_raise(
        **implicitly(
            Process(
                argv=[
                    downloaded_buf.exe,
                    "generate",
                    *config_arg,
                    *template_arg,
                    "--output",
                    output_dir,
                    *buf.gen_args,
                    *path_arg,
                ],
                input_digest=input_digest,
                immutable_input_digests=sandbox.immutable_input_digests,
                append_only_caches=sandbox.append_only_caches,
                env={**sandbox.extra_env, "PATH": os.pathsep.join(sandbox.paths)},
                description=request.description,
                level=LogLevel.DEBUG,
                output_directories=(output_dir,),
            )
        ),
    )

    # Strip the sandbox `output_dir` prefix; the buf.gen.yaml's `out:` paths land at
    # exactly the locations the user declared.
    normalized = await remove_prefix(RemovePrefix(result.output_digest, output_dir))
    return BufGenerateResult(await digest_to_snapshot(normalized))


def rules():
    return [
        *collect_rules(),
        *adhoc_process_support_rules(),
        *buf_fields.rules(),
        # `run_buf_generate` requires a `buf.lock` when `buf.yaml` has `deps:`, so the resolve
        # that generates one must exist wherever codegen does.
        *buf_lockfile.rules(),
    ]
