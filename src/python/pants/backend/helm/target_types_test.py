# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os

from pants.backend.helm import target_types
from pants.backend.helm.target_types import (
    HelmChartTarget,
    HelmUnitTestTestsGeneratorTarget,
    HelmUnitTestTestTarget,
)
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_TEMPLATE,
)
from pants.engine.addresses import Address
from pants.engine.internals.graph import _TargetParametrizations, _TargetParametrizationsRequest
from pants.engine.target import SingleSourceField, Tags
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_generate_source_targets() -> None:
    rule_runner = RuleRunner(
        rules=[
            *target_types.rules(),
            QueryRule(_TargetParametrizations, [_TargetParametrizationsRequest]),
        ],
        target_types=[HelmUnitTestTestsGeneratorTarget, HelmChartTarget],
    )

    source_root = "src/chart"
    rule_runner.write_files(
        {
            f"{source_root}/BUILD": """helm_chart(name="foo")""",
            f"{source_root}/Chart.yaml": HELM_CHART_FILE,
            f"{source_root}/values.yaml": HELM_VALUES_FILE,
            f"{source_root}/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            f"{source_root}/templates/service.yaml": K8S_SERVICE_TEMPLATE,
            f"{source_root}/tests/BUILD": "helm_unittest_tests(name='foo_tests')",
            f"{source_root}/tests/service_test.yaml": "",
        }
    )

    def gen_tgt(rel_fp: str, tags: list[str] | None = None) -> HelmUnitTestTestTarget:
        return HelmUnitTestTestTarget(
            {
                SingleSourceField.alias: rel_fp,
                Tags.alias: tags,
            },
            Address(f"{source_root}/tests", target_name="foo_tests", relative_file_path=rel_fp),
            residence_dir=os.path.dirname(os.path.join(f"{source_root}/tests", rel_fp)),
        )

    generated = rule_runner.request(
        _TargetParametrizations,
        [
            _TargetParametrizationsRequest(
                Address(f"{source_root}/tests", target_name="foo_tests"),
                description_of_origin="tests",
            )
        ],
    ).parametrizations
    assert set(generated.values()) == {
        gen_tgt("service_test.yaml"),
    }
