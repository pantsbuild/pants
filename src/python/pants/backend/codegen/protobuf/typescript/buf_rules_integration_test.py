# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os
from textwrap import dedent

import pytest

from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
)
from pants.backend.codegen.protobuf.typescript.buf_rules import (
    GenerateTypeScriptFromProtobufRequest,
)
from pants.backend.experimental.codegen.protobuf.typescript.register import (
    rules as typescript_protobuf_rules,
)
from pants.backend.javascript import package_json
from pants.backend.python import target_types_rules as python_target_types_rules
from pants.backend.python.goals import package_dists, package_pex_binary, run_pex_binary
from pants.backend.python.target_types import PexBinary, PythonSourcesGeneratorTarget
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.typescript.target_types import TypeScriptSourcesGeneratorTarget
from pants.core.target_types import FileTarget
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import Digest, DigestContents
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
    InvalidFieldException,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error

# A `protoc-gen-*` plugin that ignores its `CodeGeneratorRequest` and answers with a
# `CodeGeneratorResponse` holding one file. The response is encoded by hand so the plugin needs
# no protobuf runtime.
CODEGEN_PLUGIN = dedent(
    """\
    #!/usr/bin/env node
    const field = (number, payload) =>
      Buffer.concat([Buffer.from([(number << 3) | 2, payload.length]), payload]);
    process.stdin.resume();
    process.stdin.on("end", () => {
      const generated = Buffer.concat([
        field(1, Buffer.from("foo/person.ts")),
        field(15, Buffer.from("export {};")),
      ]);
      process.stdout.write(field(15, generated));
    });
    """
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *typescript_protobuf_rules(),
            # For the `pex_binary` codegen plugin.
            *python_target_types_rules.rules(),
            *package_pex_binary.rules(),
            *run_pex_binary.rules(),
            *pex_from_targets.rules(),
            *package_dists.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateTypeScriptFromProtobufRequest]),
            QueryRule(DigestContents, [Digest]),
            QueryRule(Addresses, [DependenciesRequest]),
        ],
        target_types=[
            TypeScriptSourcesGeneratorTarget,
            ProtobufSourcesGeneratorTarget,
            package_json.PackageJsonTarget,
            FileTarget,
            PexBinary,
            PythonSourcesGeneratorTarget,
        ],
        objects=dict(package_json.build_file_aliases().objects),
    )
    rule_runner.set_options(
        [
            "--typescript-protobuf-buf-gen-template=buf.gen.yaml",
            "--typescript-protobuf-buf-node-package-address=plugins",
        ],
        env_inherit={"PATH"},
    )
    return rule_runner


def _write_project(
    rule_runner: RuleRunner, *, proto_build: str = "protobuf_sources(protobuf_generator='buf')"
) -> None:
    rule_runner.write_files(
        {
            "buf.yaml": dedent(
                """\
            version: v2
            modules:
              - path: idl/proto
            """
            ),
            "buf.gen.yaml": dedent(
                """\
            version: v2
            plugins:
              - local: protoc-gen-test
                out: src/ts
            """
            ),
            "idl/proto/foo/person.proto": 'syntax = "proto3";\npackage foo;\nmessage Person {}\n',
            "idl/proto/foo/BUILD": proto_build,
            # An npm workspace whose member provides the plugin, so `npm ci` links it into
            # `plugins/node_modules/.bin` without fetching anything from a registry.
            "plugins/BUILD": "package_json(dependencies=['plugins/gen'])",
            "plugins/package.json": json.dumps(
                {"name": "plugins", "version": "0.0.1", "private": True, "workspaces": ["gen"]}
            ),
            "plugins/package-lock.json": json.dumps(
                {
                    "name": "plugins",
                    "version": "0.0.1",
                    "lockfileVersion": 3,
                    "requires": True,
                    "packages": {
                        "": {"name": "plugins", "version": "0.0.1", "workspaces": ["gen"]},
                        "gen": {
                            "name": "protoc-gen-test",
                            "version": "0.0.1",
                            "bin": {"protoc-gen-test": "plugin.js"},
                        },
                        "node_modules/protoc-gen-test": {"resolved": "gen", "link": True},
                    },
                }
            ),
            "plugins/gen/BUILD": dedent(
                """\
            package_json(dependencies=[":plugin"])
            file(name="plugin", source="plugin.js")
            """
            ),
            "plugins/gen/package.json": json.dumps(
                {
                    "name": "protoc-gen-test",
                    "version": "0.0.1",
                    "bin": {"protoc-gen-test": "plugin.js"},
                }
            ),
            "plugins/gen/plugin.js": CODEGEN_PLUGIN,
        }
    )
    # The plugin reaches the sandbox from source, so it needs its executable bit here; a
    # published plugin's tarball would carry one.
    os.chmod(os.path.join(rule_runner.build_root, "plugins/gen/plugin.js"), 0o755)


def _generate(rule_runner: RuleRunner) -> GeneratedSources:
    tgt = rule_runner.get_target(Address("idl/proto/foo", relative_file_path="person.proto"))
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ProtobufSourceField])]
    )
    return rule_runner.request(
        GeneratedSources,
        [GenerateTypeScriptFromProtobufRequest(protocol_sources.snapshot, tgt)],
    )


@pytest.mark.platform_specific_behavior
def test_buf_runs_plugin_from_node_package(rule_runner: RuleRunner) -> None:
    _write_project(rule_runner)
    generated = _generate(rule_runner)
    assert generated.snapshot.files == ("src/ts/foo/person.ts",)
    (content,) = rule_runner.request(DigestContents, [generated.snapshot.digest])
    assert content.content == b"export {};"


@pytest.mark.platform_specific_behavior
def test_per_target_template_overrides_typescript_option(rule_runner: RuleRunner) -> None:
    _write_project(
        rule_runner,
        proto_build="protobuf_sources(protobuf_generator='buf', buf_gen_template='buf.gen.yaml')",
    )
    rule_runner.write_files(
        {
            "idl/proto/foo/buf.gen.yaml": dedent(
                """\
                version: v2
                plugins:
                  - local: protoc-gen-test
                    out: gen_override
                """
            )
        }
    )
    assert _generate(rule_runner).snapshot.files == ("gen_override/foo/person.ts",)


# A Python `protoc-gen-*` plugin that answers with one TypeScript file, encoded by hand.
PYTHON_CODEGEN_PLUGIN = dedent(
    """\
    import sys

    def field(number, payload):
        return bytes([number << 3 | 2, len(payload)]) + payload

    sys.stdin.buffer.read()
    generated = field(1, b"foo/person.ts") + field(15, b"export {};")
    sys.stdout.buffer.write(field(15, generated))
    """
)


@pytest.mark.platform_specific_behavior
def test_plugin_from_codegen_plugins_without_node_package(rule_runner: RuleRunner) -> None:
    """A plugin written in another language generates TypeScript, with no npm package."""
    _write_project(rule_runner)
    rule_runner.write_files(
        {
            "pyplugin/plugin.py": PYTHON_CODEGEN_PLUGIN,
            "pyplugin/BUILD": dedent(
                """\
                python_sources()
                pex_binary(name="protoc-gen-test", entry_point="plugin.py")
                """
            ),
        }
    )
    rule_runner.set_options(
        [
            "--buf-codegen-plugins=['pyplugin:protoc-gen-test']",
            "--source-root-patterns=['/', 'pyplugin']",
        ],
        env_inherit={"PATH"},
    )
    generated = _generate(rule_runner)
    assert generated.snapshot.files == ("src/ts/foo/person.ts",)


@pytest.mark.platform_specific_behavior
def test_template_option_is_optional(rule_runner: RuleRunner) -> None:
    """Without `[typescript-protobuf].buf_gen_template`, the root `buf.gen.yaml` is used."""
    _write_project(rule_runner)
    rule_runner.set_options(
        ["--typescript-protobuf-buf-node-package-address=plugins"], env_inherit={"PATH"}
    )
    assert _generate(rule_runner).snapshot.files == ("src/ts/foo/person.ts",)


def test_skips_targets_not_using_buf(rule_runner: RuleRunner) -> None:
    """`export-codegen` asks every language to generate every target; protoc ones get nothing."""
    _write_project(rule_runner, proto_build="protobuf_sources()")
    assert _generate(rule_runner).snapshot.files == ()


def test_typescript_depending_on_protoc_target_fails(rule_runner: RuleRunner) -> None:
    _write_project(rule_runner, proto_build="protobuf_sources()")
    rule_runner.write_files(
        {
            "src/app/app.ts": "",
            "src/app/BUILD": "typescript_sources(dependencies=['idl/proto/foo'])",
        }
    )
    tgt = rule_runner.get_target(Address("src/app", relative_file_path="app.ts"))
    with engine_error(InvalidFieldException, contains="TypeScript can only be generated with buf"):
        rule_runner.request(Addresses, [DependenciesRequest(tgt[Dependencies])])
