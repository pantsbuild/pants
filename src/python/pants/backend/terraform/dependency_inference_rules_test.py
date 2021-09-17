# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap

import pytest

from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.terraform import dependency_inference
from pants.backend.terraform.dependency_inference import (
    ParseTerraformModuleSources,
    TerraformHcl2Parser,
)
from pants.backend.terraform.target_types import TerraformModule
from pants.build_graph.address import Address
from pants.core.util_rules import external_tool, source_files
from pants.engine.process import ProcessResult
from pants.engine.rules import QueryRule
from pants.engine.target import HydratedSources, HydrateSourcesRequest, Sources
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import RuleRunner


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(TerraformHcl2Parser.default_interpreter_constraints),
)
def test_hcl_parser_wrapper_runs(major_minor_interpreter: str) -> None:
    rule_runner = RuleRunner(
        target_types=[TerraformModule],
        rules=[
            *external_tool.rules(),
            *source_files.rules(),
            *pex_rules(),
            *dependency_inference.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(ProcessResult, [ParseTerraformModuleSources]),
        ],
    )

    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.experimental.terraform",
            f"--terraform-hcl2-parser-interpreter-constraints=['=={major_minor_interpreter}.*']",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )

    rule_runner.write_files(
        {
            "foo/BUILD": "terraform_module(name='t')\n",
            "foo/bar.tf": textwrap.dedent(
                """
                module "foo" {
                  source = "../grok"
                }
                module "bar" {
                  source = "./hello/./world"
                }
                """
            ),
        }
    )
    target = rule_runner.get_target(Address("foo", target_name="t"))
    sources = rule_runner.request(HydratedSources, [HydrateSourcesRequest(target[Sources])])
    result = rule_runner.request(
        ProcessResult,
        [
            ParseTerraformModuleSources(
                sources_digest=sources.snapshot.digest, paths=("foo/bar.tf",)
            )
        ],
    )

    lines = {line for line in result.stdout.decode("utf-8").splitlines() if line}
    assert lines == {"grok", "foo/hello/world"}
