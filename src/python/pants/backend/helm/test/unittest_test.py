# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.helm.target_types import (
    HelmChartTarget,
    HelmUnitTestTestsGeneratorTarget,
    HelmUnitTestTestTarget,
)
from pants.backend.helm.target_types import rules as helm_target_types_rules
from pants.backend.helm.test.unittest import HelmUnitTestFieldSet, HelmUnitTestRequest
from pants.backend.helm.test.unittest import rules as unittest_rules
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_TEMPLATE,
)
from pants.backend.helm.util_rules import chart
from pants.core.goals.generate_snapshots import GenerateSnapshotsResult
from pants.core.goals.test import TestResult
from pants.core.target_types import (
    FilesGeneratorTarget,
    FileTarget,
    RelocatedFiles,
    ResourcesGeneratorTarget,
)
from pants.core.target_types import rules as target_types_rules
from pants.core.util_rules import external_tool, source_files, stripped_source_files
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents
from pants.engine.rules import QueryRule
from pants.source.source_root import rules as source_root_rules
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[
            HelmChartTarget,
            HelmUnitTestTestTarget,
            HelmUnitTestTestsGeneratorTarget,
            ResourcesGeneratorTarget,
            FileTarget,
            FilesGeneratorTarget,
            RelocatedFiles,
        ],
        rules=[
            *external_tool.rules(),
            *chart.rules(),
            *unittest_rules(),
            *source_files.rules(),
            *source_root_rules(),
            *helm_target_types_rules(),
            *stripped_source_files.rules(),
            *target_types_rules(),
            QueryRule(TestResult, (HelmUnitTestRequest.Batch,)),
            QueryRule(GenerateSnapshotsResult, (HelmUnitTestFieldSet,)),
        ],
    )


def test_simple_success(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "tests/BUILD": "helm_unittest_test(name='test', source='service_test.yaml')",
            "tests/service_test.yaml": dedent(
                """\
                suite: test service
                templates:
                  - service.yaml
                values:
                  - ../values.yaml
                tests:
                  - it: should work
                    asserts:
                      - isKind:
                          of: Service
                      - equal:
                          path: spec.type
                          value: ClusterIP
                """
            ),
        }
    )

    target = rule_runner.get_target(Address("tests", target_name="test"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(TestResult, [HelmUnitTestRequest.Batch("", (field_set,), None)])

    assert result.exit_code == 0
    assert result.xml_results and result.xml_results.files
    assert result.xml_results.files == (f"{target.address.path_safe_spec}.xml",)


def test_simple_failure(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "tests/BUILD": "helm_unittest_test(name='test', source='service_test.yaml')",
            "tests/service_test.yaml": dedent(
                """\
                suite: test service
                templates:
                  - service.yaml
                values:
                  - ../values.yaml
                tests:
                  - it: should work
                    asserts:
                      - isKind:
                          of: Ingress
                      - equal:
                          path: spec.type
                          value: ClusterIP
                """
            ),
        }
    )

    target = rule_runner.get_target(Address("tests", target_name="test"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(TestResult, [HelmUnitTestRequest.Batch("", (field_set,), None)])
    assert result.exit_code == 1


def test_test_with_local_resource_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "Chart.yaml": HELM_CHART_FILE,
            "templates/configmap.yaml": dedent(
                """\
                apiVersion: v1
                kind: ConfigMap
                metadata:
                  name: foo-config
                data:
                  foo_key: {{ .Values.input }}
                """
            ),
            "tests/BUILD": dedent(
                """\
                helm_unittest_test(name="test", source="configmap_test.yaml", dependencies=[":values"])

                resources(name="values", sources=["general-values.yml"])
                """
            ),
            "tests/configmap_test.yaml": dedent(
                """\
                suite: test config map
                templates:
                  - configmap.yaml
                values:
                  - general-values.yml
                tests:
                  - it: should work
                    asserts:
                      - equal:
                          path: data.foo_key
                          value: bar_input
                """
            ),
            "tests/general-values.yml": dedent(
                """\
                input: bar_input
                """
            ),
        }
    )

    target = rule_runner.get_target(Address("tests", target_name="test"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(TestResult, [HelmUnitTestRequest.Batch("", (field_set,), None)])
    assert result.exit_code == 0


def test_test_with_non_local_resource_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/helm/BUILD": "helm_chart(name='mychart')",
            "src/helm/Chart.yaml": HELM_CHART_FILE,
            "src/helm/templates/configmap.yaml": dedent(
                """\
                apiVersion: v1
                kind: ConfigMap
                metadata:
                  name: foo-config
                data:
                  foo_key: {{ .Values.input }}
                """
            ),
            "src/helm/tests/BUILD": dedent(
                """\
                helm_unittest_test(
                  name="test",
                  source="configmap_test.yaml",
                  dependencies=["//resources/data:values"]
                )
                """
            ),
            "src/helm/tests/configmap_test.yaml": dedent(
                """\
                suite: test config map
                templates:
                  - configmap.yaml
                values:
                  - ../data/general-values.yml
                tests:
                  - it: should work
                    asserts:
                      - equal:
                          path: data.foo_key
                          value: bar_input
                """
            ),
            "resources/data/BUILD": dedent(
                """\
              resources(name="values", sources=["general-values.yml"])
              """
            ),
            "resources/data/general-values.yml": dedent(
                """\
                input: bar_input
                """
            ),
        }
    )

    source_roots = ["resources"]
    rule_runner.set_options([f"--source-root-patterns={repr(source_roots)}"])
    target = rule_runner.get_target(Address("src/helm/tests", target_name="test"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(TestResult, [HelmUnitTestRequest.Batch("", (field_set,), None)])
    assert result.exit_code == 0


def test_test_with_global_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/helm/BUILD": "helm_chart(name='mychart')",
            "src/helm/Chart.yaml": HELM_CHART_FILE,
            "src/helm/templates/configmap.yaml": dedent(
                """\
                apiVersion: v1
                kind: ConfigMap
                metadata:
                  name: foo-config
                data:
                  foo_key: {{ .Values.input }}
                """
            ),
            "src/helm/tests/BUILD": dedent(
                """\
                helm_unittest_test(
                  name="test",
                  source="configmap_test.yaml",
                  dependencies=["//files/data:values"]
                )
                """
            ),
            "src/helm/tests/configmap_test.yaml": dedent(
                """\
                suite: test config map
                templates:
                  - configmap.yaml
                values:
                  - ../files/data/general-values.yml
                tests:
                  - it: should work
                    asserts:
                      - equal:
                          path: data.foo_key
                          value: bar_input
                """
            ),
            "files/data/BUILD": dedent(
                """\
              files(name="values", sources=["general-values.yml"])
              """
            ),
            "files/data/general-values.yml": dedent(
                """\
                input: bar_input
                """
            ),
        }
    )

    target = rule_runner.get_target(Address("src/helm/tests", target_name="test"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(TestResult, [HelmUnitTestRequest.Batch("", (field_set,), None)])
    assert result.exit_code == 0


def test_test_with_relocated_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/helm/BUILD": "helm_chart(name='mychart')",
            "src/helm/Chart.yaml": HELM_CHART_FILE,
            "src/helm/templates/configmap.yaml": dedent(
                """\
                apiVersion: v1
                kind: ConfigMap
                metadata:
                  name: foo-config
                data:
                  foo_key: {{ .Values.input }}
                """
            ),
            "src/helm/tests/BUILD": dedent(
                """\
                helm_unittest_test(
                  name="test",
                  source="configmap_test.yaml",
                  dependencies=[":relocated"]
                )

                relocated_files(
                  name="relocated",
                  files_targets=["//files/data:values"],
                  src="files/data",
                  dest="tests"
                )
                """
            ),
            "src/helm/tests/configmap_test.yaml": dedent(
                """\
                suite: test config map
                templates:
                  - configmap.yaml
                values:
                  - general-values.yml
                tests:
                  - it: should work
                    asserts:
                      - equal:
                          path: data.foo_key
                          value: bar_input
                """
            ),
            "files/data/BUILD": dedent(
                """\
              files(name="values", sources=["general-values.yml"])
              """
            ),
            "files/data/general-values.yml": dedent(
                """\
                input: bar_input
                """
            ),
        }
    )

    target = rule_runner.get_target(Address("src/helm/tests", target_name="test"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(TestResult, [HelmUnitTestRequest.Batch("", (field_set,), None)])
    assert result.exit_code == 0


def test_generate_snapshots(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": "helm_chart(name='mychart')",
            "src/Chart.yaml": HELM_CHART_FILE,
            "src/values.yaml": HELM_VALUES_FILE,
            "src/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "src/tests/BUILD": "helm_unittest_test(name='test', source='service_test.yaml')",
            "src/tests/service_test.yaml": dedent(
                """\
                suite: test service
                templates:
                  - service.yaml
                values:
                  - ../values.yaml
                tests:
                  - it: should match snapshot
                    asserts:
                      - matchSnapshot: {}
                """
            ),
        }
    )

    expected_snapshot_content = dedent(
        """\
        should match snapshot:
          1: |
            apiVersion: v1
            kind: Service
            metadata:
              labels:
                chart: mychart-0.1.0
              name: RELEASE-NAME-mychart
            spec:
              ports:
                - name: test
                  port: 80
                  protocol: TCP
                  targetPort: 1223
              selector:
                app: RELEASE-NAME-mychart
              type: ClusterIP
        """
    )

    target = rule_runner.get_target(Address("src/tests", target_name="test"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(GenerateSnapshotsResult, [field_set])

    assert result.snapshot and result.snapshot.files
    assert result.snapshot.files == ("src/tests/__snapshot__/service_test.yaml.snap",)

    snapshot_contents = rule_runner.request(DigestContents, [result.snapshot.digest])
    assert len(snapshot_contents) == 1
    assert snapshot_contents[0].content.decode() == expected_snapshot_content


def test_success_with_snapshot(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": "helm_chart(name='mychart')",
            "src/Chart.yaml": HELM_CHART_FILE,
            "src/values.yaml": HELM_VALUES_FILE,
            "src/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "src/tests/BUILD": dedent(
                """\
              helm_unittest_test(name='test', source='service_test.yaml', dependencies=[":snapshots"])

              resources(name="snapshots", sources=["__snapshot__/*.snap"])
              """
            ),
            "src/tests/service_test.yaml": dedent(
                """\
                suite: test service
                templates:
                  - service.yaml
                values:
                  - ../values.yaml
                tests:
                  - it: should match snapshot
                    asserts:
                      - matchSnapshot: {}
                """
            ),
            "src/tests/__snapshot__/service_test.yaml.snap": dedent(
                """\
                should match snapshot:
                  1: |
                    apiVersion: v1
                    kind: Service
                    metadata:
                      labels:
                        chart: mychart-0.1.0
                      name: RELEASE-NAME-mychart
                    spec:
                      ports:
                        - name: test
                          port: 80
                          protocol: TCP
                          targetPort: 1223
                      selector:
                        app: RELEASE-NAME-mychart
                      type: ClusterIP
                """
            ),
        }
    )

    target = rule_runner.get_target(Address("src/tests", target_name="test"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(TestResult, [HelmUnitTestRequest.Batch("", (field_set,), None)])
    assert result.exit_code == 0


def test_failure_with_snapshot(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": "helm_chart(name='mychart')",
            "src/Chart.yaml": HELM_CHART_FILE,
            "src/values.yaml": HELM_VALUES_FILE,
            "src/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "src/tests/BUILD": dedent(
                """\
              helm_unittest_test(name='test', source='service_test.yaml', dependencies=[":snapshots"])

              resources(name="snapshots", sources=["__snapshot__/*.snap"])
              """
            ),
            "src/tests/service_test.yaml": dedent(
                """\
                suite: test service
                templates:
                  - service.yaml
                values:
                  - ../values.yaml
                tests:
                  - it: should match snapshot
                    asserts:
                      - matchSnapshot: {}
                """
            ),
            "src/tests/__snapshot__/service_test.yaml.snap": "invalid",
        }
    )

    target = rule_runner.get_target(Address("src/tests", target_name="test"))
    field_set = HelmUnitTestFieldSet.create(target)

    result = rule_runner.request(TestResult, [HelmUnitTestRequest.Batch("", (field_set,), None)])
    assert result.exit_code == 1
