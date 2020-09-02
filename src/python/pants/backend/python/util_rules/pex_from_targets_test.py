# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Optional

import pytest

from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.pex import PexRequest, PexRequirements
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.build_graph.address import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.python.python_setup import ResolveAllConstraintsOption
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *pex_from_targets.rules(),
            QueryRule(PexRequest, (PexFromTargetsRequest, OptionsBootstrapper)),
        ],
        target_types=[PythonLibrary, PythonRequirementLibrary],
    )


def test_constraints_validation(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file(
        "",
        dedent(
            """
            python_requirement_library(name="foo", requirements=["foo-bar>=0.1.2"])
            python_requirement_library(name="bar", requirements=["bar==5.5.5"])
            python_requirement_library(name="baz", requirements=["baz"])
            python_library(name="tgt", sources=[], dependencies=[":foo", ":bar", ":baz"])
            """
        ),
    )
    rule_runner.create_file(
        "constraints1.txt",
        dedent(
            """
            Foo._-BAR==1.0.0
            bar==5.5.5
            baz==2.2.2
            qux==3.4.5
        """
        ),
    )
    rule_runner.create_file(
        "constraints2.txt",
        dedent(
            """
            foo==1.0.0
            bar==5.5.5
            qux==3.4.5
        """
        ),
    )

    request = PexFromTargetsRequest(
        [Address.parse("//:tgt")], output_filename="demo.pex", internal_only=True
    )

    def get_pex_request(
        constraints_file: Optional[str], resolve_all: Optional[ResolveAllConstraintsOption]
    ) -> PexRequest:
        args = [
            "--backend-packages=pants.backend.python",
        ]
        if resolve_all:
            args.append(f"--python-setup-resolve-all-constraints={resolve_all.value}")
        if constraints_file:
            args.append(f"--python-setup-requirement-constraints={constraints_file}")
        return rule_runner.request_product(
            PexRequest, [request, create_options_bootstrapper(args=args)]
        )

    pex_req1 = get_pex_request("constraints1.txt", ResolveAllConstraintsOption.NEVER)
    assert pex_req1.requirements == PexRequirements(["foo-bar>=0.1.2", "bar==5.5.5", "baz"])

    pex_req2 = get_pex_request("constraints1.txt", ResolveAllConstraintsOption.ALWAYS)
    assert pex_req2.requirements == PexRequirements(
        ["Foo._-BAR==1.0.0", "bar==5.5.5", "baz==2.2.2", "qux==3.4.5"]
    )

    with pytest.raises(ExecutionError) as err:
        get_pex_request(None, ResolveAllConstraintsOption.ALWAYS)
    assert len(err.value.wrapped_exceptions) == 1
    assert isinstance(err.value.wrapped_exceptions[0], ValueError)
    assert (
        "[python-setup].resolve_all_constraints is set to always, so "
        "[python-setup].requirement_constraints must also be provided."
    ) in str(err.value)

    # Shouldn't error, as we don't explicitly set --resolve-all-constraints.
    get_pex_request(None, None)
