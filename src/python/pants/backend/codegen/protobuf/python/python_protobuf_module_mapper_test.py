# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.codegen.protobuf.buf import fields as buf_fields
from pants.backend.codegen.protobuf.python import additional_fields, python_protobuf_module_mapper
from pants.backend.codegen.protobuf.python.python_protobuf_module_mapper import (
    PythonProtobufMappingMarker,
)
from pants.backend.codegen.protobuf.target_types import ProtobufSourcesGeneratorTarget
from pants.backend.codegen.protobuf.target_types import rules as python_protobuf_target_types_rules
from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonMappingImpl,
    ModuleProvider,
    ModuleProviderType,
)
from pants.core.util_rules import config_files, stripped_source_files
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *buf_fields.rules(),
            *additional_fields.rules(),
            *config_files.rules(),
            *stripped_source_files.rules(),
            *python_protobuf_module_mapper.rules(),
            *python_protobuf_target_types_rules(),
            QueryRule(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker]),
        ],
        target_types=[ProtobufSourcesGeneratorTarget],
    )


def test_map_first_party_modules_to_addresses(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--source-root-patterns=['root1', 'root2', 'root3']",
            "--python-enable-resolves",
            "--python-resolves={'python-default': '', 'another-resolve': ''}",
        ]
    )
    rule_runner.write_files(
        {
            "root1/protos/f1.proto": "",
            "root1/protos/f2.proto": "",
            "root1/protos/BUILD": "protobuf_sources()",
            # These protos will result in the same module name.
            "root1/two_owners/f.proto": "",
            "root1/two_owners/BUILD": "protobuf_sources()",
            "root2/two_owners/f.proto": "",
            "root2/two_owners/BUILD": "protobuf_sources()",
            "root1/tests/f.proto": "",
            "root1/tests/BUILD": dedent(
                """\
                protobuf_sources(
                    grpc=True,
                    # This should be irrelevant to the module mapping because we strip source roots.
                    python_source_root='root3',
                    python_resolve='another-resolve',
                )
                """
            ),
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])

    def providers(addresses: list[Address]) -> tuple[ModuleProvider, ...]:
        return tuple(ModuleProvider(addr, ModuleProviderType.IMPL) for addr in addresses)

    assert result == FirstPartyPythonMappingImpl.create(
        {
            "python-default": {
                "protos.f1_pb2": providers(
                    [Address("root1/protos", relative_file_path="f1.proto")]
                ),
                "protos.f2_pb2": providers(
                    [Address("root1/protos", relative_file_path="f2.proto")]
                ),
                "two_owners.f_pb2": providers(
                    [
                        Address("root1/two_owners", relative_file_path="f.proto"),
                        Address("root2/two_owners", relative_file_path="f.proto"),
                    ]
                ),
            },
            "another-resolve": {
                "tests.f_pb2": providers([Address("root1/tests", relative_file_path="f.proto")]),
                "tests.f_pb2_grpc": providers(
                    [Address("root1/tests", relative_file_path="f.proto")]
                ),
            },
        }
    )


def test_top_level_source_root(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--source-root-patterns=['/']", "--python-enable-resolves"])
    rule_runner.write_files({"protos/f.proto": "", "protos/BUILD": "protobuf_sources()"})
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])

    def providers(addresses: list[Address]) -> tuple[ModuleProvider, ...]:
        return tuple(ModuleProvider(addr, ModuleProviderType.IMPL) for addr in addresses)

    assert result == FirstPartyPythonMappingImpl.create(
        {
            "python-default": {
                "protos.f_pb2": providers([Address("protos", relative_file_path="f.proto")])
            }
        }
    )


def test_map_grpclib_modules_to_addresses(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--source-root-patterns=['/']",
            "--python-enable-resolves",
            "--python-protobuf-grpclib-plugin",
            "--no-python-protobuf-grpcio-plugin",
        ]
    )
    rule_runner.write_files({"protos/f.proto": "", "protos/BUILD": "protobuf_sources(grpc=True)"})
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])

    def providers(addresses: list[Address]) -> tuple[ModuleProvider, ...]:
        return tuple(ModuleProvider(addr, ModuleProviderType.IMPL) for addr in addresses)

    assert result == FirstPartyPythonMappingImpl.create(
        {
            "python-default": {
                "protos.f_pb2": providers([Address("protos", relative_file_path="f.proto")]),
                "protos.f_grpc": providers([Address("protos", relative_file_path="f.proto")]),
            }
        }
    )


def test_grpc_modules_with_multiple_resolves(rule_runner: RuleRunner) -> None:
    """Verify gRPC modules are correctly mapped per resolve."""
    rule_runner.set_options(
        [
            "--source-root-patterns=['protos']",
            "--python-enable-resolves",
            "--python-resolves={'a': '', 'b': ''}",
        ]
    )
    rule_runner.write_files(
        {
            "protos/a/service.proto": "",
            "protos/a/BUILD": "protobuf_sources(grpc=True, python_resolve='a')",
            "protos/b/service.proto": "",
            "protos/b/BUILD": "protobuf_sources(grpc=True, python_resolve='b')",
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])

    def providers(addresses: list[Address]) -> tuple[ModuleProvider, ...]:
        return tuple(ModuleProvider(addr, ModuleProviderType.IMPL) for addr in addresses)

    assert result == FirstPartyPythonMappingImpl.create(
        {
            "a": {
                "a.service_pb2": providers(
                    [Address("protos/a", relative_file_path="service.proto")]
                ),
                "a.service_pb2_grpc": providers(
                    [Address("protos/a", relative_file_path="service.proto")]
                ),
            },
            "b": {
                "b.service_pb2": providers(
                    [Address("protos/b", relative_file_path="service.proto")]
                ),
                "b.service_pb2_grpc": providers(
                    [Address("protos/b", relative_file_path="service.proto")]
                ),
            },
        }
    )


def test_buf_target_registers_nothing_without_gen_yaml(rule_runner: RuleRunner) -> None:
    """Without a `buf.gen.yaml`, codegen fails and generates nothing, so nothing is registered."""
    rule_runner.set_options(["--source-root-patterns=['src/protobuf']", "--python-enable-resolves"])
    rule_runner.write_files(
        {
            "src/protobuf/foo/f.proto": "",
            "src/protobuf/foo/BUILD": ("protobuf_sources(protobuf_generator='buf')"),
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])
    assert result == FirstPartyPythonMappingImpl.create({})


def test_buf_target_uses_gen_yaml_out_directory(rule_runner: RuleRunner) -> None:
    """When `buf.gen.yaml` declares `out: src/proto`, generated paths sit under that dir.

    Here the `.proto` lives at `idl/proto/foo/bar.proto` (buf module root `idl/proto`),
    and `out: src/proto` is the Python source root. Module name is `foo.bar_pb2`.
    """
    rule_runner.set_options(
        [
            "--source-root-patterns=['idl/proto', 'src/proto']",
            "--python-enable-resolves",
        ]
    )
    rule_runner.write_files(
        {
            "idl/proto/buf.yaml": "version: v2\nmodules:\n  - path: .\n",
            "idl/proto/buf.gen.yaml": (
                "version: v2\nplugins:\n  - protoc_builtin: python\n    out: src/proto\n"
            ),
            "idl/proto/foo/bar.proto": "",
            "idl/proto/foo/BUILD": ("protobuf_sources(protobuf_generator='buf')"),
        }
    )
    # The discovery glob for `buf.gen.yaml` only checks the repo root, so we stage one
    # there too; alternatively a per-target field override would be used.
    rule_runner.write_files(
        {
            "buf.gen.yaml": (
                "version: v2\nplugins:\n  - protoc_builtin: python\n    out: src/proto\n"
            ),
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])
    assert result == FirstPartyPythonMappingImpl.create(
        {
            "python-default": {
                "foo.bar_pb2": (
                    ModuleProvider(
                        Address("idl/proto/foo", relative_file_path="bar.proto"),
                        ModuleProviderType.IMPL,
                    ),
                )
            }
        }
    )


def test_buf_target_default_remote_plugin_matches_with_version_pin(
    rule_runner: RuleRunner,
) -> None:
    """The default `python_buf_plugin = buf.build/protocolbuffers/python` matches a
    `remote:` plugin entry even when the entry includes a `:vXX.X` version suffix."""
    rule_runner.set_options(["--source-root-patterns=['/']", "--python-enable-resolves"])
    rule_runner.write_files(
        {
            "buf.yaml": "version: v2\nmodules:\n  - path: .\n",
            "buf.gen.yaml": (
                "version: v2\n"
                "plugins:\n"
                "  - remote: buf.build/protocolbuffers/python:v34.1\n"
                "    out: gen\n"
            ),
            "protos/svc.proto": "",
            "protos/BUILD": "protobuf_sources(protobuf_generator='buf')",
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])
    assert result == FirstPartyPythonMappingImpl.create(
        {
            "python-default": {
                "gen.protos.svc_pb2": (
                    ModuleProvider(
                        Address("protos", relative_file_path="svc.proto"),
                        ModuleProviderType.IMPL,
                    ),
                )
            }
        }
    )


def test_buf_target_connectrpc_plugin_registers_connect_modules(
    rule_runner: RuleRunner,
) -> None:
    """A `connectrpc/python` plugin entry registers `_connect.py` modules
    automatically — no subsystem opt-in, plugin presence in `buf.gen.yaml` is
    sufficient.

    Repo layout (mirrors the connectrpc.com getting-started example):
      - `buf.yaml` declares the buf module at `company/proto`.
      - `buf.gen.yaml` runs the protobuf-python and connectrpc-python remote plugins,
        sending pb2 output to `company/proto/gen` and connect output to `company/protogen`.
      - The proto file lives at `company/proto/services/test/v1/service.proto`.
      - Pants has source roots at `company/proto/gen` and `company/protogen`, so the
        generated Python modules are `services.test.v1.service_pb2` and
        `services.test.v1.service_connect`.
    """
    rule_runner.set_options(
        [
            "--source-root-patterns=['company/proto/gen', 'company/protogen']",
            "--python-enable-resolves",
        ]
    )
    rule_runner.write_files(
        {
            "buf.yaml": dedent(
                """\
                version: v2
                modules:
                  - path: company/proto
                """
            ),
            "buf.gen.yaml": dedent(
                """\
                version: v2
                managed:
                  enabled: true
                plugins:
                  - remote: buf.build/protocolbuffers/python:v34.1
                    out: company/proto/gen
                  - remote: buf.build/protocolbuffers/pyi:v34.1
                    out: company/proto/gen
                  - remote: buf.build/connectrpc/python:v0.1.0
                    out: company/protogen
                """
            ),
            "company/proto/services/test/v1/service.proto": "",
            "company/proto/services/test/v1/BUILD": ("protobuf_sources(protobuf_generator='buf')"),
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])

    address = Address("company/proto/services/test/v1", relative_file_path="service.proto")
    provider = (ModuleProvider(address, ModuleProviderType.IMPL),)
    assert result == FirstPartyPythonMappingImpl.create(
        {
            "python-default": {
                "services.test.v1.service_pb2": provider,
                "services.test.v1.service_connect": provider,
            }
        }
    )


def test_buf_target_grpc_plugin_registers_pb2_grpc(rule_runner: RuleRunner) -> None:
    """A grpc-python plugin entry in `buf.gen.yaml` registers `_pb2_grpc` modules."""
    rule_runner.set_options(
        [
            "--source-root-patterns=['/']",
            "--python-enable-resolves",
        ]
    )
    rule_runner.write_files(
        {
            "buf.yaml": "version: v2\nmodules:\n  - path: .\n",
            "buf.gen.yaml": (
                "version: v2\n"
                "plugins:\n"
                "  - protoc_builtin: python\n"
                "    out: gen\n"
                "  - local: protoc-gen-grpc-python\n"
                "    out: gen\n"
            ),
            "protos/svc.proto": "",
            "protos/BUILD": "protobuf_sources(grpc=True, protobuf_generator='buf')",
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])

    def providers(addresses: list[Address]) -> tuple[ModuleProvider, ...]:
        return tuple(ModuleProvider(addr, ModuleProviderType.IMPL) for addr in addresses)

    address = Address("protos", relative_file_path="svc.proto")
    assert result == FirstPartyPythonMappingImpl.create(
        {
            "python-default": {
                "gen.protos.svc_pb2": providers([address]),
                "gen.protos.svc_pb2_grpc": providers([address]),
            }
        }
    )


def test_buf_target_per_target_template_override(rule_runner: RuleRunner) -> None:
    """Two buf targets pointing at different `buf_gen_template`s land at different `out:`s."""
    rule_runner.set_options(
        [
            "--source-root-patterns=['/']",
            "--python-enable-resolves",
        ]
    )
    rule_runner.write_files(
        {
            "buf.yaml": "version: v2\nmodules:\n  - path: .\n",
            "a/protos/svc.proto": "",
            "a/protos/buf.gen.yaml": (
                "version: v2\nplugins:\n  - protoc_builtin: python\n    out: gen_a\n"
            ),
            "a/protos/BUILD": (
                "protobuf_sources(protobuf_generator='buf', buf_gen_template='buf.gen.yaml')"
            ),
            "b/protos/svc.proto": "",
            "b/protos/buf.gen.yaml": (
                "version: v2\nplugins:\n  - protoc_builtin: python\n    out: gen_b\n"
            ),
            "b/protos/BUILD": (
                "protobuf_sources(protobuf_generator='buf', buf_gen_template='buf.gen.yaml')"
            ),
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])

    def providers(addresses: list[Address]) -> tuple[ModuleProvider, ...]:
        return tuple(ModuleProvider(addr, ModuleProviderType.IMPL) for addr in addresses)

    # `buf.yaml` declares one module spanning the repo (`path: .`). Each proto's
    # module-relative path is its full repo path, so the generated module is
    # `<out>/<full proto path>`.
    assert result == FirstPartyPythonMappingImpl.create(
        {
            "python-default": {
                "gen_a.a.protos.svc_pb2": providers(
                    [Address("a/protos", relative_file_path="svc.proto")]
                ),
                "gen_b.b.protos.svc_pb2": providers(
                    [Address("b/protos", relative_file_path="svc.proto")]
                ),
            }
        }
    )


def test_buf_target_grpc_field_is_no_op(rule_runner: RuleRunner) -> None:
    """`grpc=True` on a buf target has no effect on which suffixes are registered;
    plugin presence in `buf.gen.yaml` is the sole determinant."""
    rule_runner.set_options(["--source-root-patterns=['/']", "--python-enable-resolves"])
    rule_runner.write_files(
        {
            "buf.yaml": "version: v2\nmodules:\n  - path: .\n",
            # Only `_pb2` plugin — no service plugin.
            "buf.gen.yaml": ("version: v2\nplugins:\n  - protoc_builtin: python\n    out: gen\n"),
            "protos/svc.proto": "",
            # `grpc=True` would normally register `_pb2_grpc`; on the buf path it's
            # ignored and only `_pb2` (matched by the python plugin) is registered.
            "protos/BUILD": "protobuf_sources(grpc=True, protobuf_generator='buf')",
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])
    address = Address("protos", relative_file_path="svc.proto")
    provider = (ModuleProvider(address, ModuleProviderType.IMPL),)
    assert result == FirstPartyPythonMappingImpl.create(
        {"python-default": {"gen.protos.svc_pb2": provider}}
    )


def test_buf_target_unpinned_remote_plugin_succeeds_via_registry(
    rule_runner: RuleRunner,
) -> None:
    """Inference does not enforce pinning — that's codegen's job. An unpinned
    `remote:` entry whose plugin id is in Pants's built-in registry is matched
    by id, the suffix is found, and the module is registered. (Codegen will
    fill in the registry's default `:vX.Y:revN` pin before invoking buf.)"""
    rule_runner.set_options(["--source-root-patterns=['/']", "--python-enable-resolves"])
    rule_runner.write_files(
        {
            "buf.yaml": "version: v2\nmodules:\n  - path: .\n",
            "buf.gen.yaml": (
                "version: v2\n"
                "plugins:\n"
                "  - remote: buf.build/protocolbuffers/python\n"  # no version pin
                "    out: gen\n"
            ),
            "protos/svc.proto": "",
            "protos/BUILD": "protobuf_sources(protobuf_generator='buf')",
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])
    address = Address("protos", relative_file_path="svc.proto")
    provider = (ModuleProvider(address, ModuleProviderType.IMPL),)
    assert result == FirstPartyPythonMappingImpl.create(
        {"python-default": {"gen.protos.svc_pb2": provider}}
    )


def test_buf_target_extra_plugin_suffixes_override(rule_runner: RuleRunner) -> None:
    """`[python-protobuf].extra_buf_plugin_suffixes` lets users teach Pants about
    custom or forked plugins without modifying the registry."""
    rule_runner.set_options(
        [
            "--source-root-patterns=['/']",
            "--python-enable-resolves",
            (
                "--python-protobuf-extra-buf-plugin-suffixes="
                '{"remote:myorg.example.com/internal/python-fork": "_pb2"}'
            ),
        ]
    )
    rule_runner.write_files(
        {
            "buf.yaml": "version: v2\nmodules:\n  - path: .\n",
            "buf.gen.yaml": (
                "version: v2\n"
                "plugins:\n"
                "  - remote: myorg.example.com/internal/python-fork:v1.0\n"
                "    out: gen\n"
            ),
            "protos/svc.proto": "",
            "protos/BUILD": "protobuf_sources(protobuf_generator='buf')",
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])
    address = Address("protos", relative_file_path="svc.proto")
    provider = (ModuleProvider(address, ModuleProviderType.IMPL),)
    assert result == FirstPartyPythonMappingImpl.create(
        {"python-default": {"gen.protos.svc_pb2": provider}}
    )


@pytest.mark.parametrize("plugin", ["protoc-gen-grpclib_python", "protoc-gen-python_grpc"])
def test_buf_target_grpclib_plugin_names(rule_runner: RuleRunner, plugin: str) -> None:
    """grpclib installs its plugin under both names."""
    rule_runner.set_options(["--source-root-patterns=['/']", "--python-enable-resolves"])
    rule_runner.write_files(
        {
            "buf.yaml": "version: v2\nmodules:\n  - path: .\n",
            "buf.gen.yaml": f"version: v2\nplugins:\n  - local: {plugin}\n    out: gen\n",
            "protos/svc.proto": "",
            "protos/BUILD": "protobuf_sources(protobuf_generator='buf')",
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])
    provider = (
        ModuleProvider(Address("protos", relative_file_path="svc.proto"), ModuleProviderType.IMPL),
    )
    assert result == FirstPartyPythonMappingImpl.create(
        {"python-default": {"gen.protos.svc_grpc": provider}}
    )


def test_buf_target_extra_plugin_suffixes_rejects_unknown_suffix(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--source-root-patterns=['/']",
            '--python-protobuf-extra-buf-plugin-suffixes={"local:protoc-gen-mine": "pb2"}',
        ]
    )
    rule_runner.write_files(
        {
            "buf.gen.yaml": "version: v2\nplugins:\n  - local: protoc-gen-mine\n    out: gen\n",
            "protos/svc.proto": "",
            "protos/BUILD": "protobuf_sources(protobuf_generator='buf')",
        }
    )
    with engine_error(ValueError, contains="has 'pb2' for `local:protoc-gen-mine`"):
        rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])


def test_mypy_protobuf_modules_with_resolves(rule_runner: RuleRunner) -> None:
    """Verify mypy-protobuf does not change module mapping across resolves."""
    rule_runner.set_options(
        [
            "--source-root-patterns=['protos']",
            "--python-enable-resolves",
            "--python-resolves={'a': '', 'b': ''}",
            "--python-protobuf-mypy-plugin",
        ]
    )
    rule_runner.write_files(
        {
            "protos/a/model.proto": "",
            "protos/a/BUILD": "protobuf_sources(python_resolve='a')",
            "protos/b/model.proto": "",
            "protos/b/BUILD": "protobuf_sources(python_resolve='b')",
        }
    )
    result = rule_runner.request(FirstPartyPythonMappingImpl, [PythonProtobufMappingMarker()])

    def providers(addresses: list[Address]) -> tuple[ModuleProvider, ...]:
        return tuple(ModuleProvider(addr, ModuleProviderType.IMPL) for addr in addresses)

    assert result == FirstPartyPythonMappingImpl.create(
        {
            "a": {
                "a.model_pb2": providers([Address("protos/a", relative_file_path="model.proto")])
            },
            "b": {
                "b.model_pb2": providers([Address("protos/b", relative_file_path="model.proto")])
            },
        }
    )
