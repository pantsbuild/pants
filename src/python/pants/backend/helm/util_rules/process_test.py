# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.helm.util_rules import process
from pants.backend.helm.util_rules.process import HelmProcess
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[],
        rules=[
            *process.rules(),
            QueryRule(HelmBinary, ()),
            QueryRule(Process, (HelmProcess,)),
        ],
    )


def test_create_helm_process(rule_runner: RuleRunner) -> None:
    helm_binary = rule_runner.request(HelmBinary, [])

    helm_argv = ["foo"]
    helm_process = HelmProcess(
        helm_argv,
        input_digest=EMPTY_DIGEST,
        description="Test Helm process",
        extra_immutable_input_digests={"foo_digest": EMPTY_DIGEST},
        extra_env={"FOO_ENV": "1"},
        output_directories=["foo_out"],
        cache_scope=ProcessCacheScope.ALWAYS,
    )
    process = rule_runner.request(Process, [helm_process])

    assert process.argv == (helm_binary.path, *helm_argv)
    assert process.description == helm_process.description
    assert process.level == helm_process.level
    assert process.input_digest == helm_process.input_digest
    assert process.immutable_input_digests == FrozenDict(
        {**helm_binary.immutable_input_digests, **helm_process.extra_immutable_input_digests}
    )
    assert process.env == FrozenDict({**helm_binary.env, **helm_process.extra_env})
    assert process.output_directories == helm_process.output_directories
    assert process.cache_scope == helm_process.cache_scope


# _EMPTY_BYTES = "".encode("utf-8")


# def test_create_helm_evaluation_process(rule_runner: RuleRunner) -> None:
#     value_filenames = ["values.yaml", "override-values.yaml", "more-values.yaml"]
#     value_files_digest = rule_runner.request(
#         Digest,
#         [CreateDigest([FileContent(filename, _EMPTY_BYTES) for filename in value_filenames])],
#     )
#     value_files_snapshot = rule_runner.request(Snapshot, [value_files_digest])

#     eval_process = HelmRenderProcess(
#         cmd=HelmRenderCmd.TEMPLATE,
#         chart_path="chart",
#         chart_digest=EMPTY_DIGEST,
#         release_name="test",
#         namespace="ns",
#         skip_crds=True,
#         no_hooks=True,
#         values_snapshot=value_files_snapshot,
#         values={"foo": "bar"},
#         extra_argv=["--bar"],
#         message="Test Helm process",
#         description="Foo evaluated",
#         output_directory="foo_out",
#     )

#     helm_binary = rule_runner.request(HelmBinary, [])
#     expected_argv = [
#         helm_binary.path,
#         HelmRenderCmd.TEMPLATE.value,
#         eval_process.release_name,
#         eval_process.chart_path,
#         "--description",
#         f'"{eval_process.description}"',
#         "--namespace",
#         eval_process.namespace,
#         "--skip-crds",
#         "--no-hooks",
#         "--values",
#         "more-values.yaml,values.yaml,override-values.yaml",
#         "--set",
#         'foo="bar"',
#         *eval_process.extra_argv,
#     ]

#     process = rule_runner.request(Process, [eval_process])
#     assert process.argv == tuple(expected_argv)
#     assert process.level == LogLevel.INFO
#     assert process.cache_scope == ProcessCacheScope.SUCCESSFUL
#     assert process.description == eval_process.message

#     input_snapshot = rule_runner.request(Snapshot, [process.input_digest])
#     for filename in value_filenames:
#         assert filename in input_snapshot.files
