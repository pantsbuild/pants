# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.dependency_inference.parse_python_dependencies import (
    PythonDependencyVisitor,
    PythonDependencyVisitorRequest,
    get_scripts_digest,
)
from pants.backend.python.framework.django.detect_apps import DjangoApps
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class DjangoDependencyVisitorRequest(PythonDependencyVisitorRequest):
    pass


_scripts_package = "pants.backend.python.framework.django.scripts"


@rule
async def django_parser_script(
    _: DjangoDependencyVisitorRequest,
    django_apps: DjangoApps,
) -> PythonDependencyVisitor:
    django_apps_digest = await Get(
        Digest, CreateDigest([FileContent("apps.json", django_apps.to_json())])
    )
    scripts_digest = await get_scripts_digest(_scripts_package, ["dependency_visitor.py"])
    digest = await Get(Digest, MergeDigests([django_apps_digest, scripts_digest]))
    return PythonDependencyVisitor(
        digest=digest,
        classname=f"{_scripts_package}.dependency_visitor.DjangoDependencyVisitor",
        env=FrozenDict({}),
    )


def rules():
    return [
        UnionRule(PythonDependencyVisitorRequest, DjangoDependencyVisitorRequest),
        *collect_rules(),
    ]
