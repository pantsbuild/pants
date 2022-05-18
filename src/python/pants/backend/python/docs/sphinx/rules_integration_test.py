# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from textwrap import dedent

import pytest

from pants.backend.python.docs.sphinx.rules import SphinxPackageFieldSet
from pants.backend.python.docs.sphinx.rules import rules as sphinx_rules
from pants.backend.python.docs.sphinx.target_types import SphinxProjectTarget
from pants.core.goals.package import BuiltPackage
from pants.engine.addresses import Address
from pants.engine.fs import Snapshot
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner

SIMPLE_INDEX_RST = dedent(
    """\
    Welcome!
    =============================

    .. toctree::
       :maxdepth: 2
       :caption: Contents:
    """
)

SIMPLE_CONF_PY = dedent(
    """\
    project = 'Tests'
    copyright = '2022'
    author = 'pantsy'
    templates_path = ['_templates']
    html_static_path = ['_static']
    """
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sphinx_rules(),
            QueryRule(BuiltPackage, [SphinxPackageFieldSet]),
        ],
        target_types=[SphinxProjectTarget],
    )
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def assert_project_built(
    rule_runner: RuleRunner, addr: Address, *, expected_output_path: str
) -> None:
    tgt = rule_runner.get_target(addr)
    field_set = SphinxPackageFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    assert len(result.artifacts) == 1
    assert result.artifacts[0].relpath == expected_output_path

    snapshot = rule_runner.request(Snapshot, [result.digest])
    assert os.path.join(expected_output_path, "index.html") in snapshot.files


@pytest.mark.platform_specific_behavior
def test_build_root_project(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "conf.py": SIMPLE_CONF_PY,
            "index.rst": SIMPLE_INDEX_RST,
            "BUILD": "sphinx_project(name='sphinx')",
        }
    )
    assert_project_built(
        rule_runner, Address("", target_name="sphinx"), expected_output_path="sphinx"
    )


def test_subdir_project(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "subdir/conf.py": SIMPLE_CONF_PY,
            "subdir/index.rst": SIMPLE_INDEX_RST,
            "subdir/BUILD": "sphinx_project(name='sphinx')",
        }
    )
    assert_project_built(
        rule_runner, Address("subdir", target_name="sphinx"), expected_output_path="subdir/sphinx"
    )
