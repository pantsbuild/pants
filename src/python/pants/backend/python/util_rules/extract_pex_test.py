# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable

import pytest

from pants.backend.python.util_rules import extract_pex, pex
from pants.backend.python.util_rules.extract_pex import ExtractedPexDistributions
from pants.backend.python.util_rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.core.util_rules.pants_environment import PantsEnvironment
from pants.engine.fs import EMPTY_DIGEST, Snapshot
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *extract_pex.rules(),
            *pex.rules(),
            QueryRule(Pex, [PexRequest, PantsEnvironment]),
            QueryRule(ExtractedPexDistributions, [Pex]),
        ]
    )


def get_distributions(
    rule_runner: RuleRunner, *, requirements: Iterable[str], constraints: Iterable[str]
) -> ExtractedPexDistributions:
    # NB: The constraints are important for determinism.
    rule_runner.create_file("constraints.txt", "\n".join(constraints))

    pex_request = PexRequest(
        output_filename="test.pex",
        requirements=PexRequirements(requirements),
        interpreter_constraints=PexInterpreterConstraints([">=3.6"]),
        internal_only=True,
    )
    options_bootstrapper = create_options_bootstrapper(
        args=[
            "--backend-packages=pants.backend.python",
            "--python-setup-requirement-constraints=constraints.txt",
        ]
    )
    built_pex = rule_runner.request(Pex, [pex_request, options_bootstrapper, PantsEnvironment()])
    return rule_runner.request(ExtractedPexDistributions, [built_pex])


def test_extract_distributions(rule_runner: RuleRunner) -> None:
    # We use these requirements because all of their wheels are prebuilt (faster test) and they all
    # work with any Python 3 interpreter, rather than something interpreter-specific like `cp36`
    # (deterministic test).
    constraints = ["six==1.15.0", "t61codec==1.0.1", "x690==0.2.0"]
    result = get_distributions(
        rule_runner,
        requirements=["x690"],
        constraints=constraints,
    )

    assert len(result.wheel_directory_paths) == len(constraints)
    # Note that we expect the `wheel_directory_paths` to have been sorted.
    assert result.wheel_directory_paths[0] == ".deps/six-1.15.0-py2.py3-none-any.whl"
    assert result.wheel_directory_paths[1] == ".deps/t61codec-1.0.1-py2.py3-none-any.whl"
    assert result.wheel_directory_paths[2] == ".deps/x690-0.2.0-py3-none-any.whl"

    # Spot check that some expected files are included.
    result_snapshot = rule_runner.request(Snapshot, [result.digest])
    for f in [
        ".deps/t61codec-1.0.1-py2.py3-none-any.whl/t61codec-1.0.1.dist-info/INSTALLER",
        ".deps/six-1.15.0-py2.py3-none-any.whl/six.py",
        ".deps/x690-0.2.0-py3-none-any.whl/x690/types.py",
    ]:
        assert f in result_snapshot.files


def test_extract_distributions_none_found(rule_runner: RuleRunner) -> None:
    result = get_distributions(rule_runner, requirements=[], constraints=[])
    assert not result.wheel_directory_paths
    assert result.digest == EMPTY_DIGEST
