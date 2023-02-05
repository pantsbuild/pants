# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.dependency_inference.parse_python_dependencies import (
    PythonDependencyVisitor,
    PythonDependencyVisitorRequest,
    _get_scripts_digest,
)
from pants.backend.python.target_types import PythonSourceField
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class DjangoDependencyVisitorRequest(PythonDependencyVisitorRequest):
    pass


_scripts_package = "pants.backend.python.framework.django.scripts"


@rule
async def general_parser_script(
    _: DjangoDependencyVisitorRequest,
) -> PythonDependencyVisitor:
    digest = await _get_scripts_digest(_scripts_package, ["django_dependency_visitor.py"])
    return PythonDependencyVisitor(
        digest=digest,
        classname=f"{_scripts_package}.django_dependency_visitor.DjangoDependencyVisitor",
        env=FrozenDict({}),
    )


@dataclass(frozen=True)
class DjangoMigrationDependenciesInferenceFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField


def rules():
    return [
        UnionRule(PythonDependencyVisitorRequest, DjangoDependencyVisitorRequest),
        *collect_rules(),
    ]
