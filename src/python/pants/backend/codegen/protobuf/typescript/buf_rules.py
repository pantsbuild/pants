# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from collections.abc import Iterable

from pants.backend.codegen.protobuf.buf.generate import BufGenerateRequest, run_buf_generate
from pants.backend.codegen.protobuf.buf.generate import rules as buf_generate_rules
from pants.backend.codegen.protobuf.target_types import ProtobufSourceField
from pants.backend.codegen.protobuf.typescript.subsystem import TypeScriptProtobufSubsystem
from pants.backend.javascript.install_node_package import (
    InstalledNodePackageRequest,
    add_sources_to_installed_node_package,
)
from pants.backend.javascript.subsystems.nodejs import NodeJSProcessEnvironment
from pants.backend.typescript.target_types import TypeScriptSourceField
from pants.core.util_rules.adhoc_process_support import ExtraSandboxContents
from pants.engine.addresses import AddressInput
from pants.engine.internals.build_files import resolve_address
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.target import GeneratedSources, GenerateSourcesRequest
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


class GenerateTypeScriptFromProtobufRequest(GenerateSourcesRequest):
    input = ProtobufSourceField
    output = TypeScriptSourceField


async def _node_plugin_toolchain(
    package_address_str: str, options_scope: str, node_environment: NodeJSProcessEnvironment
) -> ExtraSandboxContents:
    """Install `buf_node_package_address` and put its `node_modules/.bin` and Node.js on PATH."""
    package_address = await resolve_address(
        **implicitly(
            {
                AddressInput.parse(
                    package_address_str,
                    description_of_origin=(
                        f"the `[{options_scope}].buf_node_package_address` option"
                    ),
                ): AddressInput
            }
        )
    )
    # The template's plugins are the package's `node_modules/.bin` entries, and a plugin
    # defined in the package itself also needs the package's sources. Codegen is off: the
    # package depends on the protobuf targets, and generating them would re-enter this rule.
    installed_package = await add_sources_to_installed_node_package(
        InstalledNodePackageRequest(package_address, enable_codegen=False)
    )
    env = node_environment.to_env_dict(
        {
            "PATH": os.path.join(
                "{chroot}", installed_package.project_env.root_dir, "node_modules", ".bin"
            )
        }
    )
    return ExtraSandboxContents(
        digest=installed_package.digest,
        paths=(env.pop("PATH"),),
        immutable_input_digests=FrozenDict(node_environment.immutable_digest()),
        append_only_caches=FrozenDict(node_environment.append_only_caches),
        extra_env=FrozenDict(env),
    )


@rule(desc="Generate TypeScript from Protobuf via `buf generate`", level=LogLevel.DEBUG)
async def generate_typescript_from_protobuf(
    request: GenerateTypeScriptFromProtobufRequest,
    typescript_protobuf: TypeScriptProtobufSubsystem,
    node_environment: NodeJSProcessEnvironment,
) -> GeneratedSources:
    target = request.protocol_target
    package_address = typescript_protobuf.buf_node_package_address
    toolchain = (
        await _node_plugin_toolchain(
            package_address, typescript_protobuf.options_scope, node_environment
        )
        if package_address
        else None
    )
    result = await run_buf_generate(
        BufGenerateRequest(
            target=target,
            language_template=typescript_protobuf.language_gen_template,
            description=f"Generating TypeScript from Protobuf via buf for {target.address}.",
            toolchain=toolchain,
        ),
        **implicitly(),
    )
    return GeneratedSources(result.snapshot)


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *buf_generate_rules(),
        UnionRule(GenerateSourcesRequest, GenerateTypeScriptFromProtobufRequest),
    )
