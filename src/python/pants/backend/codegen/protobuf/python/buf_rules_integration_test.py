# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.codegen.protobuf import protobuf_dependency_inference
from pants.backend.codegen.protobuf.protobuf_dependency_inference import (
    InferProtobufDependencies,
    ProtobufDependencyInferenceFieldSet,
)
from pants.backend.codegen.protobuf.python import additional_fields
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    rules as protobuf_subsystem_rules,
)
from pants.backend.codegen.protobuf.python.register import rules as python_protobuf_backend_rules
from pants.backend.codegen.protobuf.python.rules import GeneratePythonFromProtobufRequest
from pants.backend.codegen.protobuf.python.rules import rules as protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as protobuf_target_types_rules
from pants.backend.python import target_types_rules as python_target_types_rules
from pants.backend.python.dependency_inference import module_mapper
from pants.core.target_types import rules as core_target_types_rules
from pants.core.util_rules import stripped_source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.target import (
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
    InferredDependencies,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner

# A minimal `buf.gen.yaml` template that invokes the python plugin built into protoc.
# `buf` shells out to `protoc` for `protoc_builtin` plugins, so `protoc` must be on PATH.
BUF_GEN_YAML = dedent(
    """\
    version: v2
    plugins:
      - protoc_builtin: python
        out: src/proto
    """
)

BUF_YAML = dedent(
    """\
    version: v2
    modules:
      - path: idl/proto
    """
)

SIMPLE_PROTO = dedent(
    """\
    syntax = "proto3";
    package foo;
    message Person {
      string name = 1;
      int32 id = 2;
    }
    """
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *protobuf_rules(),
            *python_protobuf_backend_rules(),
            *protobuf_dependency_inference.rules(),
            *protobuf_subsystem_rules(),
            *additional_fields.rules(),
            *protobuf_target_types_rules(),
            *python_target_types_rules.rules(),
            *stripped_source_files.rules(),
            *module_mapper.rules(),
            *core_target_types_rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GeneratePythonFromProtobufRequest]),
            QueryRule(InferredDependencies, [InferProtobufDependencies]),
            QueryRule(TransitiveTargets, [TransitiveTargetsRequest]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
        ],
        target_types=[ProtobufSourcesGeneratorTarget],
    )


def _assert_generates(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: set[str],
    source_roots: list[str],
) -> None:
    rule_runner.set_options(
        [
            f"--source-root-patterns={repr(source_roots)}",
            "--no-python-protobuf-infer-runtime-dependency",
        ],
        env_inherit={"PATH"},
    )
    tgt = rule_runner.get_target(address)
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ProtobufSourceField])]
    )
    generated = rule_runner.request(
        GeneratedSources,
        [GeneratePythonFromProtobufRequest(protocol_sources.snapshot, tgt)],
    )
    assert set(generated.snapshot.files) == expected_files


@pytest.mark.platform_specific_behavior
def test_buf_generates_python_at_out_directory(rule_runner: RuleRunner) -> None:
    """`out: src/proto` in `buf.gen.yaml` lands generated files at `src/proto/...`."""
    rule_runner.write_files(
        {
            "buf.yaml": BUF_YAML,
            "buf.gen.yaml": BUF_GEN_YAML,
            "idl/proto/foo/person.proto": SIMPLE_PROTO,
            "idl/proto/foo/BUILD": ("protobuf_sources(protobuf_generator='buf')"),
        }
    )
    _assert_generates(
        rule_runner,
        Address("idl/proto/foo", relative_file_path="person.proto"),
        expected_files={"src/proto/foo/person_pb2.py"},
        source_roots=["idl/proto", "src/proto"],
    )


@pytest.mark.platform_specific_behavior
def test_buf_per_target_template_override(rule_runner: RuleRunner) -> None:
    """Per-target `buf_gen_template` overrides the global discovered template."""
    rule_runner.write_files(
        {
            "buf.yaml": BUF_YAML,
            # Repo-root template that would write to `gen_default/...` if it were used.
            "buf.gen.yaml": dedent(
                """\
                version: v2
                plugins:
                  - protoc_builtin: python
                    out: gen_default
                """
            ),
            "idl/proto/foo/buf.gen.yaml": dedent(
                """\
                version: v2
                plugins:
                  - protoc_builtin: python
                    out: gen_override
                """
            ),
            "idl/proto/foo/person.proto": SIMPLE_PROTO,
            "idl/proto/foo/BUILD": (
                "protobuf_sources(protobuf_generator='buf', buf_gen_template='buf.gen.yaml')"
            ),
        }
    )
    _assert_generates(
        rule_runner,
        Address("idl/proto/foo", relative_file_path="person.proto"),
        expected_files={"gen_override/foo/person_pb2.py"},
        source_roots=["idl/proto", "gen_override"],
    )


@pytest.mark.platform_specific_behavior
def test_buf_generates_python_with_remote_plugin(rule_runner: RuleRunner) -> None:
    """A `remote:` plugin (fetched from the buf.build registry) is invoked over the
    network at codegen time and must produce output the same way `protoc_builtin:`
    plugins do. Pinned to a specific version so the test is deterministic."""
    rule_runner.write_files(
        {
            "buf.yaml": BUF_YAML,
            "buf.gen.yaml": dedent(
                """\
                version: v2
                plugins:
                  - remote: buf.build/protocolbuffers/python:v34.1
                    out: gen_remote
                """
            ),
            "idl/proto/foo/person.proto": SIMPLE_PROTO,
            "idl/proto/foo/BUILD": "protobuf_sources(protobuf_generator='buf')",
        }
    )
    _assert_generates(
        rule_runner,
        Address("idl/proto/foo", relative_file_path="person.proto"),
        expected_files={"gen_remote/foo/person_pb2.py"},
        source_roots=["idl/proto", "gen_remote"],
    )


@pytest.mark.platform_specific_behavior
def test_buf_only_sends_transitive_closure_to_sandbox(rule_runner: RuleRunner) -> None:
    """Codegen for one proto target must (a) include protos it transitively
    imports, even from separate folders with separate BUILD files, and (b)
    *not* include unrelated siblings in the same buf module.

    Verified end-to-end:
    - The target's proto imports a sibling-folder proto. If our `transitive_targets.closure`
      missed the import, that sibling wouldn't reach the sandbox and buf would fail to
      compile (unresolved import).
    - An unrelated sibling proto is deliberately malformed — buf would reject it if it
      ever saw it. Codegen succeeding proves it was filtered out.

    Matters for monorepo scale: a buf module with thousands of `.proto` files
    must not send all of them to every per-target codegen invocation."""
    rule_runner.write_files(
        {
            "buf.yaml": BUF_YAML,
            "buf.gen.yaml": BUF_GEN_YAML,
            # The target's own proto, importing a sibling-folder proto.
            "idl/proto/foo/person.proto": dedent(
                """\
                syntax = "proto3";
                package foo;
                import "common/address.proto";
                message Person {
                  string name = 1;
                  common.Address address = 2;
                }
                """
            ),
            "idl/proto/foo/BUILD": "protobuf_sources(protobuf_generator='buf')",
            # The dep, in its own folder + BUILD — Pants's proto-dep inference
            # picks it up via the `import` statement above.
            "idl/proto/common/address.proto": dedent(
                """\
                syntax = "proto3";
                package common;
                message Address {
                  string street = 1;
                  string city = 2;
                }
                """
            ),
            "idl/proto/common/BUILD": "protobuf_sources(protobuf_generator='buf')",
            # Unrelated proto in yet another folder, with its own BUILD. Must
            # NOT reach the sandbox — deliberately malformed so buf would error
            # on it if our closure leaked.
            "idl/proto/bar/garbage.proto": "this is not a valid proto file !!!",
            "idl/proto/bar/BUILD": "protobuf_sources(protobuf_generator='buf')",
        }
    )
    _assert_generates(
        rule_runner,
        Address("idl/proto/foo", relative_file_path="person.proto"),
        expected_files={"src/proto/foo/person_pb2.py"},
        source_roots=["idl/proto", "src/proto"],
    )

    # And the dep inferrer reports the same shape: address.proto is in, garbage is out.
    person_addr = Address("idl/proto/foo", relative_file_path="person.proto")
    person_tgt = rule_runner.get_target(person_addr)
    inferred = rule_runner.request(
        InferredDependencies,
        [InferProtobufDependencies(ProtobufDependencyInferenceFieldSet.create(person_tgt))],
    )
    inferred_addrs = set(inferred.include)
    assert Address("idl/proto/common", relative_file_path="address.proto") in inferred_addrs
    assert Address("idl/proto/bar", relative_file_path="garbage.proto") not in inferred_addrs


@pytest.mark.platform_specific_behavior
def test_buf_isolates_per_proto_within_one_build_file(rule_runner: RuleRunner) -> None:
    """Cache-invalidation correctness for the case where two protos share a
    `protobuf_sources()` glob: per-file targets must remain independent so a
    monorepo with thousands of protos under one BUILD doesn't pay a cache tax
    on every edit.

    Verifies both:
    - **Structural** (the input digest): `garbage.proto` is *not* in
      person.proto's `transitive_targets.closure` or its `SourceFiles` digest.
      If those bytes aren't part of person's input, no change to garbage can
      bust person's cache.
    - **E2E**: codegen for `person.proto` succeeds (closure isolates), and
      codegen for the malformed `garbage.proto` *fails* — sanity-checking
      that the malformed-proto trick has teeth so the negative half of the
      structural assertion is meaningful."""
    from pants.engine.internals.scheduler import ExecutionError

    rule_runner.write_files(
        {
            "buf.yaml": BUF_YAML,
            "buf.gen.yaml": BUF_GEN_YAML,
            # Both protos under one BUILD file's `protobuf_sources()` glob.
            "idl/proto/foo/person.proto": SIMPLE_PROTO,
            "idl/proto/foo/garbage.proto": "this is not a valid proto file !!!",
            "idl/proto/foo/BUILD": "protobuf_sources(protobuf_generator='buf')",
        }
    )
    rule_runner.set_options(
        [
            "--source-root-patterns=['idl/proto', 'src/proto']",
            "--no-python-protobuf-infer-runtime-dependency",
        ],
        env_inherit={"PATH"},
    )

    person_addr = Address("idl/proto/foo", relative_file_path="person.proto")
    garbage_addr = Address("idl/proto/foo", relative_file_path="garbage.proto")

    # Structural: garbage isn't in person's closure or source-files digest.
    transitive = rule_runner.request(TransitiveTargets, [TransitiveTargetsRequest([person_addr])])
    proto_addresses = {
        tgt.address for tgt in transitive.closure if tgt.has_field(ProtobufSourceField)
    }
    assert person_addr in proto_addresses
    assert garbage_addr not in proto_addresses
    sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(
                tgt[ProtobufSourceField]
                for tgt in transitive.closure
                if tgt.has_field(ProtobufSourceField)
            )
        ],
    )
    assert "idl/proto/foo/person.proto" in sources.snapshot.files
    assert "idl/proto/foo/garbage.proto" not in sources.snapshot.files

    # E2E: person's codegen succeeds; garbage's fails (sanity-check the trick).
    person_tgt = rule_runner.get_target(person_addr)
    person_hydrated = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(person_tgt[ProtobufSourceField])]
    )
    generated = rule_runner.request(
        GeneratedSources,
        [GeneratePythonFromProtobufRequest(person_hydrated.snapshot, person_tgt)],
    )
    assert set(generated.snapshot.files) == {"src/proto/foo/person_pb2.py"}

    garbage_tgt = rule_runner.get_target(garbage_addr)
    garbage_hydrated = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(garbage_tgt[ProtobufSourceField])]
    )
    with pytest.raises(ExecutionError):
        rule_runner.request(
            GeneratedSources,
            [GeneratePythonFromProtobufRequest(garbage_hydrated.snapshot, garbage_tgt)],
        )


@pytest.mark.platform_specific_behavior
def test_buf_generates_full_tree_when_dependency_inference_off(rule_runner: RuleRunner) -> None:
    """With `[protoc].dependency_inference` off, `buf generate` drops `--path` and
    runs against the full proto tree, so every per-target invocation produces the
    same complete output set.

    This is what lets plugins that emit package-level files (e.g. betterproto2's
    one `__init__.py` per package) generate identical, dedupeable bytes regardless
    of which sibling target triggered the run. Here we verify the general
    mechanism: generating for a single proto yields *both* siblings' outputs
    because `--path` is no longer scoping the run."""
    address_proto = dedent(
        """\
        syntax = "proto3";
        package foo;
        message Address {
          string street = 1;
        }
        """
    )
    rule_runner.write_files(
        {
            "buf.yaml": BUF_YAML,
            "buf.gen.yaml": BUF_GEN_YAML,
            "idl/proto/foo/person.proto": SIMPLE_PROTO,
            "idl/proto/foo/address.proto": address_proto,
            "idl/proto/foo/BUILD": "protobuf_sources(protobuf_generator='buf')",
        }
    )
    rule_runner.set_options(
        [
            "--source-root-patterns=['idl/proto', 'src/proto']",
            "--no-python-protobuf-infer-runtime-dependency",
            # Inference off -> `add_dependencies_on_all_siblings` on -> full tree in
            # each sandbox -> buf rule drops `--path`.
            "--no-protoc-dependency-inference",
        ],
        env_inherit={"PATH"},
    )

    person_tgt = rule_runner.get_target(Address("idl/proto/foo", relative_file_path="person.proto"))
    person_hydrated = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(person_tgt[ProtobufSourceField])]
    )
    generated = rule_runner.request(
        GeneratedSources,
        [GeneratePythonFromProtobufRequest(person_hydrated.snapshot, person_tgt)],
    )
    # No `--path`, so generating for `person` emits the whole package, not just
    # `person_pb2.py`.
    assert set(generated.snapshot.files) == {
        "src/proto/foo/person_pb2.py",
        "src/proto/foo/address_pb2.py",
    }


@pytest.mark.platform_specific_behavior
def test_buf_codegen_fails_without_buf_lock_when_deps_declared(
    rule_runner: RuleRunner,
) -> None:
    """`buf.yaml` declaring `deps:` without a sibling `buf.lock` is rejected at
    codegen time with a friendly error pointing at `pants generate-lockfiles
    --resolve=…`."""
    from pants.backend.codegen.protobuf.buf.config import MissingBufLockError
    from pants.engine.internals.scheduler import ExecutionError

    rule_runner.write_files(
        {
            "buf.yaml": dedent(
                """\
                version: v2
                modules:
                  - path: idl/proto
                deps:
                  - buf.build/bufbuild/protovalidate
                """
            ),
            "buf.gen.yaml": BUF_GEN_YAML,
            # No buf.lock — codegen must reject this before invoking buf.
            "idl/proto/foo/person.proto": SIMPLE_PROTO,
            "idl/proto/foo/BUILD": "protobuf_sources(protobuf_generator='buf')",
        }
    )
    rule_runner.set_options(
        [
            "--source-root-patterns=['idl/proto', 'src/proto']",
            "--no-python-protobuf-infer-runtime-dependency",
        ],
        env_inherit={"PATH"},
    )
    tgt = rule_runner.get_target(Address("idl/proto/foo", relative_file_path="person.proto"))
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ProtobufSourceField])]
    )
    with pytest.raises(ExecutionError) as excinfo:
        rule_runner.request(
            GeneratedSources,
            [GeneratePythonFromProtobufRequest(protocol_sources.snapshot, tgt)],
        )
    cause_types = {type(c).__name__ for c in excinfo.value.wrapped_exceptions}
    assert MissingBufLockError.__name__ in cause_types
    msg = str(excinfo.value)
    assert "buf.build/bufbuild/protovalidate" in msg
    assert "pants generate-lockfiles --resolve=" in msg


@pytest.mark.platform_specific_behavior
def test_default_protoc_path_still_works(rule_runner: RuleRunner) -> None:
    """Regression: `protobuf_generator` unset (default `protoc`) is unchanged."""
    rule_runner.write_files(
        {
            "src/protobuf/foo/person.proto": SIMPLE_PROTO,
            "src/protobuf/foo/BUILD": "protobuf_sources()",
        }
    )
    _assert_generates(
        rule_runner,
        Address("src/protobuf/foo", relative_file_path="person.proto"),
        expected_files={"src/protobuf/foo/person_pb2.py"},
        source_roots=["src/protobuf"],
    )
