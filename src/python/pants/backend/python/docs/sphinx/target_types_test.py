# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.docs.sphinx.target_types import (
    SphinxProjectSourcesField,
    SphinxProjectTarget,
)
from pants.engine.addresses import Address
from pants.engine.target import HydratedSources, HydrateSourcesRequest, InvalidFieldException
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


def test_conf_py_file_validation() -> None:
    rule_runner = RuleRunner(
        rules=[QueryRule(HydratedSources, [HydrateSourcesRequest])],
        target_types=[SphinxProjectTarget],
    )
    rule_runner.write_files(
        {
            "no_py/BUILD": "sphinx_project()",
            "too_many_py/conf.py": "",
            "too_many_py/f1.py": "",
            "too_many_py/f2.py": "",
            "too_many_py/BUILD": "sphinx_project(sources=['*.py'])",
            "wrong_file/not_conf.py": "",
            "wrong_file/BUILD": "sphinx_project(sources=['*.py'])",
        }
    )
    for d in ("no_py", "too_many_py", "wrong_file"):
        with engine_error(InvalidFieldException):
            tgt = rule_runner.get_target(Address(d))
            rule_runner.request(
                HydratedSources, [HydrateSourcesRequest(tgt[SphinxProjectSourcesField])]
            )
