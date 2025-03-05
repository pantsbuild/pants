from pants.backend.codegen.python_format_string.target_types import (
    PythonFormatStringSourceField,
    PythonFormatStringTarget,
)
from textwrap import dedent
from pants.backend.codegen.python_format_string.k8s import rules as k8s_rules
from pants.backend.codegen.python_format_string.k8s.rules import (
    GenerateK8sSourceFromPythonFormatStringRequest,
)
from pants.engine.fs import DigestContents
from pants.engine.internals.native_engine import Address
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources, HydrateSourcesRequest, HydratedSources
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


import pytest


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            PythonFormatStringTarget,
        ],
        rules=[
            *k8s_rules.rules(),
            QueryRule(HydratedSources, (HydrateSourcesRequest,)),
            QueryRule(GeneratedSources, (GenerateK8sSourceFromPythonFormatStringRequest,)),
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@pytest.fixture
def input_files() -> dict[str, str]:
    return {
        "BUILD": dedent("""\
            python_format_string(
                name="deployment",
                source="deployment.yaml",
                values={"VERSION": "1.2.3"}
            )
        """),
        "deployment.yaml": dedent("""\
            kind: Deployment
            ...
            image: my-image:{VERSION}
        """),
    }


@pytest.fixture
def expected_files() -> dict[str, str]:
    return {
        "deployment.rendered": dedent("""\
            kind: Deployment
            ...
            image: my-image:1.2.3
        """)
    }


def test_generate_k8s(
    rule_runner: RuleRunner,
    input_files: dict[str, str],
    expected_files: dict[str, str],
) -> None:
    rule_runner.write_files(input_files)
    address = Address("", target_name="deployment")
    target = rule_runner.get_target(address)
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(target[PythonFormatStringSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources,
        [GenerateK8sSourceFromPythonFormatStringRequest(protocol_sources.snapshot, target)],
    )
    assert generated_sources.snapshot.files == tuple(expected_files)
    contents = rule_runner.request(DigestContents, [generated_sources.snapshot.digest])
    assert {f.path: f.content.decode("utf-8") for f in contents} == expected_files
