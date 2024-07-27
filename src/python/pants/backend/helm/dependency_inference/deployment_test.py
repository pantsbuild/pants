# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from unittest.mock import MagicMock

import pytest

from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.helm.dependency_inference import deployment
from pants.backend.helm.dependency_inference.deployment import (
    AnalyseHelmDeploymentRequest,
    FirstPartyHelmDeploymentMapping,
    FirstPartyHelmDeploymentMappingRequest,
    HelmDeploymentReport,
    ImageReferenceResolver,
    InferHelmDeploymentDependenciesRequest,
)
from pants.backend.helm.dependency_inference.subsystem import (
    HelmInferSubsystem,
    UnownedDependencyError,
    UnownedHelmDependencyUsage,
)
from pants.backend.helm.target_types import (
    HelmChartTarget,
    HelmDeploymentFieldSet,
    HelmDeploymentTarget,
)
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_TEMPLATE,
)
from pants.backend.helm.util_rules import chart, tool
from pants.backend.python.util_rules import pex
from pants.build_graph.address import MaybeAddress, ResolveError
from pants.core.util_rules import config_files, external_tool, stripped_source_files
from pants.engine import process
from pants.engine.addresses import Address
from pants.engine.internals.graph import rules as graph_rules
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.engine.target import InferredDependencies
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmDeploymentTarget, DockerImageTarget],
        rules=[
            *config_files.rules(),
            *external_tool.rules(),
            *chart.rules(),
            *deployment.rules(),
            *graph_rules(),
            *pex.rules(),
            *process.rules(),
            *stripped_source_files.rules(),
            *tool.rules(),
            QueryRule(FirstPartyHelmDeploymentMapping, (FirstPartyHelmDeploymentMappingRequest,)),
            QueryRule(HelmDeploymentReport, (AnalyseHelmDeploymentRequest,)),
            QueryRule(InferredDependencies, (InferHelmDeploymentDependenciesRequest,)),
        ],
    )


def test_deployment_dependencies_report(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/values.yaml": HELM_VALUES_FILE,
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/mychart/templates/service.yaml": K8S_SERVICE_TEMPLATE,
            "src/mychart/templates/pod.yaml": dedent(
                """\
                apiVersion: v1
                kind: Pod
                metadata:
                  name: {{ template "fullname" . }}
                  labels:
                    chart: "{{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}"
                spec:
                  containers:
                    - name: myapp-container
                      image: busybox:1.28
                  initContainers:
                    - name: init-service
                      image: busybox:1.29
                    - name: init-db
                      image: example.com/containers/busybox:1.28
                """
            ),
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart')",
        }
    )

    source_root_patterns = ("/src/*",)
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"], env_inherit=PYTHON_BOOTSTRAP_ENV
    )

    target = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    field_set = HelmDeploymentFieldSet.create(target)

    dependencies_report = rule_runner.request(
        HelmDeploymentReport, [AnalyseHelmDeploymentRequest(field_set)]
    )

    expected_container_refs = [
        "busybox:1.28",
        "busybox:1.29",
        "example.com/containers/busybox:1.28",
    ]

    assert len(dependencies_report.all_image_refs) == 3
    assert set(dependencies_report.all_image_refs) == set(expected_container_refs)


def test_inject_chart_into_deployment_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/values.yaml": HELM_VALUES_FILE,
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart')",
        }
    )

    source_root_patterns = ("src/*",)
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    deployment_addr = Address("src/deployment", target_name="foo")
    tgt = rule_runner.get_target(deployment_addr)
    field_set = HelmDeploymentFieldSet.create(tgt)

    inferred_dependencies = rule_runner.request(
        InferredDependencies,
        [InferHelmDeploymentDependenciesRequest(field_set)],
    )

    assert len(inferred_dependencies.include) == 1
    assert list(inferred_dependencies.include)[0] == Address("src/mychart")


def make_pod_yaml(idx: int):
    return dedent(
        """\
        apiVersion: v1
        kind: Pod
        metadata:
          name: {{ template "fullname" . }}
          labels:
            chart: "{{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}"
        spec:
          containers:
            - name: myapp-container
              image: {{ .Values.container.image_ref%s }}
        """
        % idx
    )


@pytest.mark.parametrize("correct_target_name", [True, False])
def test_resolve_relative_docker_addresses_to_deployment(
    rule_runner: RuleRunner, correct_target_name: bool
) -> None:
    if correct_target_name:
        target_name = "myapp"
    else:
        target_name = "myoop"

    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/values.yaml": dedent(
                """\
                container:
                  image_ref: docker/image:latest
                """
            ),
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/mychart/templates/pod.yaml": "---".join(make_pod_yaml(idx) for idx in range(4)),
            "src/deployment/BUILD": dedent(
                f"""\
                docker_image(name="myapp0")
                docker_image(name="myapp1")

                helm_deployment(
                    name="foo",
                    chart="//src/mychart",
                    values={{
                        "container.image_ref0": ":{target_name}0",  # bare target
                        "container.image_ref1": "//src/deployment:{target_name}1",  # absolute target
                        "container.image_ref2": "./subdir:{target_name}2",  # target in subdir
                        "container.image_ref3": "busybox:latest",  # a normal docker container
                        "container.image_ref_4": "./baddir:{target_name}",
                    }}
                )
                """
            ),
            "src/deployment/Dockerfile": "FROM busybox:1.28",
            "src/deployment/subdir/BUILD": """docker_image(name="myapp2")""",
            "src/deployment/subdir/Dockerfile": "FROM busybox:1.28",
        }
    )

    source_root_patterns = ("src/*",)
    rule_runner.set_options(
        [
            f"--source-root-patterns={repr(source_root_patterns)}",
            "--helm-infer-external-docker-images=busybox",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    deployment_addr = Address("src/deployment", target_name="foo")
    tgt = rule_runner.get_target(deployment_addr)
    field_set = HelmDeploymentFieldSet.create(tgt)

    def make_request():
        return rule_runner.request(
            FirstPartyHelmDeploymentMapping, [FirstPartyHelmDeploymentMappingRequest(field_set)]
        )

    if correct_target_name:
        expected = [
            (":myapp0", Address("src/deployment", target_name="myapp0")),
            ("//src/deployment:myapp1", Address("src/deployment", target_name="myapp1")),
            ("./subdir:myapp2", Address("src/deployment/subdir", target_name="myapp2")),
        ]
        assert list(make_request().indexed_docker_addresses.values()) == expected

    else:
        with pytest.raises(ExecutionError) as e:
            make_request()
        assert isinstance(e.value.wrapped_exceptions[0], UnownedDependencyError)


def test_resolving_docker_image() -> None:
    valid_target = "testprojects/src/helm/deployment:myapp"
    image_with_target_name = "testprojects/src/helm/deployment/myapp:1.0.0"
    target_not_found = "//testprojects/src/helm/deployment/oops:docker"
    target_wrong_type = "testprojects/src/helm/deployment:file"
    docker_with_registry = "quay.io/kiwigrid/k8s-sidecar:1.14.2"
    resolver = ImageReferenceResolver(
        create_subsystem(
            HelmInferSubsystem,
            unowned_dependency_behavior=UnownedHelmDependencyUsage.RaiseError,
            external_docker_images=["busybox", "quay.io/kiwigrid/k8s-sidecar"],
        ),
        {
            "busybox:latest": MaybeAddress(val=ResolveError("short error")),
            "python:latest": MaybeAddress(val=ResolveError("short error")),
            valid_target: MaybeAddress(
                val=Address("testprojects/src/helm/deployment", target_name="myapp")
            ),
            image_with_target_name: MaybeAddress(val=ResolveError("short error")),
            "testprojects/src/helm/deployment:myaapp": MaybeAddress(
                val=Address("testprojects/src/helm/deployment", target_name="myaapp")
            ),
            target_not_found: MaybeAddress(val=ResolveError("short error")),
            target_wrong_type: MaybeAddress(
                val=Address("testprojects/src/helm/deployment", target_name="file")
            ),
            docker_with_registry: MaybeAddress(val=ResolveError("short error")),
        },
        {
            Address("testprojects/src/helm/deployment", target_name="myapp"),
        },
    )

    def do_resolve(image_ref):
        """Perform the image resolution, raise any errors, and reset the resolver."""
        try:
            res = resolver.image_ref_to_actual_address(image_ref)
            resolver.report_errors()
            return res
        finally:
            resolver.errors = []

    assert (
        do_resolve("busybox:latest") is None
    ), "image in known 3rd party should have no resolution"

    with pytest.raises(UnownedDependencyError):
        # image not in known 3rd party should have no resolution
        do_resolve("python:latest")

    assert do_resolve(valid_target) == (
        valid_target,
        Address("testprojects/src/helm/deployment", target_name="myapp"),
    ), "A valid target should resolve correctly"

    with pytest.raises(UnownedDependencyError):
        # an invalid target that looks like a normal target should not resolve
        do_resolve(image_with_target_name)

    with pytest.raises(UnownedDependencyError):
        # something that is obviously a Pants target that isn't found should not resolve
        do_resolve(target_not_found)

    with pytest.raises(UnownedDependencyError):
        # a target which is not a docker_image should not resolve
        do_resolve(target_wrong_type)

    assert (
        do_resolve(docker_with_registry) is None
    ), "image with registry in known 3rd party should have no resolution"


def test_resolving_docker_image_no_thirdparty() -> None:
    resolver = ImageReferenceResolver(
        create_subsystem(HelmInferSubsystem, external_docker_images=["*"]),
        {
            "busybox:latest": MaybeAddress(val=ResolveError("short error")),
        },
        set(),
    )
    resolver._handle_missing_docker_image = MagicMock(return_value=None)  # type: ignore[method-assign]
    assert (
        resolver.image_ref_to_actual_address("busybox:latest") is None
    ), "with 3rdparty permitting everything, anything 3rdparty should not resolve"
    assert (
        not resolver._handle_missing_docker_image.call_args_list
    ), "with 3rdparty permitting everything, we should not warn"


def test_inject_deployment_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/values.yaml": HELM_VALUES_FILE,
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/mychart/templates/pod.yaml": dedent(
                """\
                apiVersion: v1
                kind: Pod
                metadata:
                  name: {{ template "fullname" . }}
                  labels:
                    chart: "{{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}"
                spec:
                  containers:
                    - name: myapp-container
                      image: src/image:myapp
                """
            ),
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart')",
            "src/image/BUILD": "docker_image(name='myapp')",
            "src/image/Dockerfile": "FROM busybox:1.28",
        }
    )

    source_root_patterns = ("src/*",)
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    deployment_addr = Address("src/deployment", target_name="foo")
    tgt = rule_runner.get_target(deployment_addr)
    field_set = HelmDeploymentFieldSet.create(tgt)

    expected_image_ref = "src/image:myapp"
    expected_dependency_addr = Address("src/image", target_name="myapp")

    mapping = rule_runner.request(
        FirstPartyHelmDeploymentMapping, [FirstPartyHelmDeploymentMappingRequest(field_set)]
    )
    assert list(mapping.indexed_docker_addresses.values()) == [
        (expected_image_ref, expected_dependency_addr)
    ]

    inferred_dependencies = rule_runner.request(
        InferredDependencies,
        [InferHelmDeploymentDependenciesRequest(field_set)],
    )

    # The Helm chart dependency is part of the inferred dependencies
    assert len(inferred_dependencies.include) == 2
    assert expected_dependency_addr in inferred_dependencies.include


def test_disambiguate_docker_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/values.yaml": HELM_VALUES_FILE,
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/mychart/templates/pod.yaml": dedent(
                """\
                apiVersion: v1
                kind: Pod
                metadata:
                  name: {{ template "fullname" . }}
                  labels:
                    chart: "{{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}"
                spec:
                  containers:
                    - name: myapp-container
                      image: registry/image:latest
                """
            ),
            "src/deployment/BUILD": dedent(
                """\
                helm_deployment(
                    name="foo",
                    chart="//src/mychart",
                    dependencies=[
                        "!//registry/image:latest",
                    ]
                )
                """
            ),
            "registry/image/BUILD": "docker_image(name='latest')",
            "registry/image/Dockerfile": "FROM busybox:1.28",
        }
    )

    source_root_patterns = ("/", "src/*")
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    deployment_addr = Address("src/deployment", target_name="foo")
    tgt = rule_runner.get_target(deployment_addr)

    inferred_dependencies = rule_runner.request(
        InferredDependencies,
        [InferHelmDeploymentDependenciesRequest(HelmDeploymentFieldSet.create(tgt))],
    )

    # Assert only the Helm chart dependency has been inferred
    assert len(inferred_dependencies.include) == 1
    assert set(inferred_dependencies.include) == {Address("src/mychart")}
