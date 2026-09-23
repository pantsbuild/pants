# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from pants.backend.codegen.protobuf.buf.config import (
    MissingBufLockError,
    gen_template_request_for_target,
    parse_buf_yaml_deps,
    resolved_template_path,
    synthesize_pinned_buf_gen_yaml,
)
from pants.backend.codegen.protobuf.buf.subsystem import BufSubsystem
from pants.backend.codegen.protobuf.protoc import Protoc
from pants.backend.codegen.protobuf.python.additional_fields import PythonSourceRootField
from pants.backend.codegen.protobuf.target_types import ProtobufSourceField
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.external_tool import download_external_tool
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.fs import CreateDigest, Directory, FileContent, MergeDigests, RemovePrefix
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
from pants.engine.target import GeneratedSources, Target, TransitiveTargetsRequest
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratePythonFromProtobufViaBufRequest:
    protocol_target: Target


@rule(desc="Generate Python from Protobuf via `buf generate`", level=LogLevel.DEBUG)
async def generate_python_from_protobuf_via_buf(
    request: GeneratePythonFromProtobufViaBufRequest,
    buf: BufSubsystem,
    protoc: Protoc,
    platform: Platform,
) -> GeneratedSources:
    target = request.protocol_target

    if target.get(PythonSourceRootField).value is not None:
        logger.warning(
            "`python_source_root` is set on %s but `protobuf_generator='buf'`; "
            "the field is ignored — output paths come from the `out:` field of "
            "`buf.gen.yaml`.",
            target.address,
        )

    output_dir = "_generated_files"
    create_output_dir_request = create_digest(CreateDigest([Directory(output_dir)]))

    # Buf needs all transitive `.proto` sources to resolve imports, even though only
    # the target's own files are passed via `--path`.
    transitive_targets = await transitive_targets_get(
        TransitiveTargetsRequest([target.address]), **implicitly()
    )

    # Unlike the protoc path, buf operates on original (unstripped) paths because
    # the buf module root is determined by `buf.yaml`'s location, not by Pants source
    # roots.
    all_sources_request = determine_source_files(
        SourceFilesRequest(
            tgt[ProtobufSourceField]
            for tgt in transitive_targets.closure
            if tgt.has_field(ProtobufSourceField)
        )
    )
    target_sources_request = determine_source_files(
        SourceFilesRequest([target[ProtobufSourceField]])
    )

    download_buf_request = download_external_tool(buf.get_request(platform))
    download_protoc_request = download_external_tool(protoc.get_request(platform))
    config_files_request = find_config_file(buf.config_request)
    gen_template_files_request = find_config_file(gen_template_request_for_target(target, buf))

    (
        downloaded_buf,
        downloaded_protoc,
        empty_output_dir,
        all_sources,
        target_sources,
        config_files,
        gen_template_files,
    ) = await concurrently(
        download_buf_request,
        download_protoc_request,
        create_output_dir_request,
        all_sources_request,
        target_sources_request,
        config_files_request,
        gen_template_files_request,
    )

    # If the user's `buf.yaml` declares BSR `deps:`, require a sibling
    # `buf.lock` so codegen is reproducible. The lock is what pins each dep to
    # an exact commit; without it, buf would resolve to whatever is currently
    # latest on the BSR.
    config_yaml_paths = [
        p for p in config_files.snapshot.files if os.path.basename(p) == "buf.yaml"
    ]
    config_lock_paths = {
        p for p in config_files.snapshot.files if os.path.basename(p) == "buf.lock"
    }
    if config_yaml_paths:
        yaml_path = config_yaml_paths[0]
        config_dcs = await get_digest_contents(config_files.snapshot.digest)
        yaml_content = next(
            (dc.content for dc in config_dcs if dc.path == yaml_path),
            b"",
        )
        deps = parse_buf_yaml_deps(yaml_content)
        expected_lock = os.path.join(os.path.dirname(yaml_path), "buf.lock")
        if deps and expected_lock not in config_lock_paths:
            resolve_name = os.path.dirname(yaml_path) or "buf"
            raise MissingBufLockError(
                f"`{yaml_path}` declares `deps:` ({', '.join(deps)}) but no "
                f"`{expected_lock}` was found. Pants requires a `buf.lock` so "
                f"BSR deps are pinned and codegen is reproducible.\n\n"
                f"Run `pants generate-lockfiles --resolve={resolve_name}` to "
                f"create it."
            )

    # Resolve every `remote:` plugin to an exact `:vX.Y:revN` pin before
    # invoking buf. Unpinned entries that can be filled in from
    # `DEFAULT_PLUGIN_PINS` (or the user's `[buf].extra_plugin_pins`) get a
    # default; unknown unpinned entries raise. The resulting yaml is written
    # into a fresh digest that replaces the user's `buf.gen.yaml` in the
    # sandbox, so buf sees a hermetic, fully-pinned config.
    gen_template_digest = gen_template_files.snapshot.digest
    if gen_template_files.snapshot.files:
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
        if synthesized != gen_template_content:
            gen_template_digest = await create_digest(
                CreateDigest(
                    [FileContent(gen_template_path, synthesized)],
                )
            )

    input_digest = await merge_digests(
        MergeDigests(
            (
                all_sources.snapshot.digest,
                empty_output_dir,
                downloaded_buf.digest,
                config_files.snapshot.digest,
                gen_template_digest,
            )
        )
    )

    config_arg = ["--config", buf.config] if buf.config else []
    template_path = resolved_template_path(target, buf)
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

    argv = [
        downloaded_buf.exe,
        "generate",
        *config_arg,
        *template_arg,
        "--output",
        output_dir,
        *buf.gen_args,
        *path_arg,
    ]

    # Expose `protoc` (and any plugin binaries co-located with it) on PATH so
    # `buf generate` can resolve `protoc_builtin:` and `local: [protoc]` plugin
    # entries.
    protoc_relpath = "__protoc"
    protoc_bin_dir = os.path.join(protoc_relpath, os.path.dirname(downloaded_protoc.exe))

    result = await execute_process_or_raise(
        **implicitly(
            Process(
                argv=argv,
                input_digest=input_digest,
                immutable_input_digests={protoc_relpath: downloaded_protoc.digest},
                env={"PATH": protoc_bin_dir},
                description=f"Generating Python from Protobuf via buf for {target.address}.",
                level=LogLevel.DEBUG,
                output_directories=(output_dir,),
            )
        ),
    )

    # Strip the sandbox `output_dir` prefix; the buf.gen.yaml's `out:` paths land at
    # exactly the locations the user declared.
    normalized = await remove_prefix(RemovePrefix(result.output_digest, output_dir))
    snapshot = await digest_to_snapshot(normalized)
    return GeneratedSources(snapshot)


def rules():
    return collect_rules()
