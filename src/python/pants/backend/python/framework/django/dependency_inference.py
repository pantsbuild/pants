# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from pathlib import PurePath

from pants.backend.python import dependency_inference
from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonAssetPaths,
    ParsedPythonImportInfo,
    ParsedPythonImports,
    PythonFileDependencies,
)
from pants.backend.python.dependency_inference.rules import (
    ImportOwnerStatus,
    PythonImportDependenciesInferenceFieldSet,
    ResolvedParsedPythonDependenciesRequest,
    resolve_parsed_dependencies,
)
from pants.backend.python.framework.django.detect_apps import DjangoApps
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import EntryPoint
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, VenvPexProcess, create_venv_pex
from pants.base.specs import FileGlobSpec, RawSpecs
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import strip_source_roots
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.graph import resolve_targets
from pants.engine.intrinsics import create_digest
from pants.engine.process import execute_process_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.resources import read_resource


class InferDjangoDependencies(InferDependenciesRequest):
    infer_from = PythonImportDependenciesInferenceFieldSet


_visitor_resource = "scripts/dependency_visitor.py"
_implicit_dependency_packages = (
    "management.commands",
    "migrations",
)


async def _django_migration_dependencies(
    request: InferDjangoDependencies,
    python_setup: PythonSetup,
    django_apps: DjangoApps,
) -> InferredDependencies:
    stripped_sources = await strip_source_roots(
        **implicitly(SourceFilesRequest([request.field_set.source]))
    )
    assert len(stripped_sources.snapshot.files) == 1

    file_content = FileContent("__visitor.py", read_resource(__name__, _visitor_resource))
    visitor_digest = await create_digest(CreateDigest([file_content]))
    venv_pex = await create_venv_pex(
        **implicitly(
            PexRequest(
                output_filename="__visitor.pex",
                internal_only=True,
                main=EntryPoint("__visitor"),
                interpreter_constraints=InterpreterConstraints.create_from_field_sets(
                    [request.field_set], python_setup=python_setup
                ),
                sources=visitor_digest,
            )
        )
    )
    process_result = await execute_process_or_raise(
        **implicitly(
            VenvPexProcess(
                venv_pex,
                argv=[stripped_sources.snapshot.files[0]],
                description=f"Determine Django app dependencies for {request.field_set.address}",
                input_digest=stripped_sources.snapshot.digest,
                level=LogLevel.DEBUG,
            )
        )
    )
    # See in script for where we explicitly encoded as utf8. Even though utf8 is the
    # default for decode(), we make that explicit here for emphasis.
    process_output = process_result.stdout.decode("utf8") or "{}"
    modules = [
        f"{django_apps.label_to_name[label]}.migrations.{migration}"
        for label, migration in json.loads(process_output)
        if label in django_apps.label_to_name
    ]
    resolve = request.field_set.resolve.normalized_value(python_setup)

    resolved_dependencies = await resolve_parsed_dependencies(
        ResolvedParsedPythonDependenciesRequest(
            request.field_set,
            PythonFileDependencies(
                ParsedPythonImports(
                    (module, ParsedPythonImportInfo(0, False)) for module in modules
                ),
                ParsedPythonAssetPaths(),
            ),
            resolve,
        ),
        **implicitly(),
    )

    return InferredDependencies(
        sorted(
            address
            for result in resolved_dependencies.resolve_results.values()
            if result.status in (ImportOwnerStatus.unambiguous, ImportOwnerStatus.disambiguated)
            for address in result.address
        )
    )


async def _django_app_implicit_dependencies(
    request: InferDjangoDependencies,
    python_setup: PythonSetup,
    django_apps: DjangoApps,
) -> InferredDependencies:
    file_path = request.field_set.source.file_path
    apps = [
        django_app for django_app in django_apps.values() if django_app.config_file == file_path
    ]
    if not apps:
        return InferredDependencies([])

    app_package = apps[0].name

    implicit_dependency_packages = [
        f"{app_package}.{subpackage}" for subpackage in _implicit_dependency_packages
    ]

    resolve = request.field_set.resolve.normalized_value(python_setup)

    resolved_dependencies = await resolve_parsed_dependencies(
        ResolvedParsedPythonDependenciesRequest(
            request.field_set,
            PythonFileDependencies(
                ParsedPythonImports(
                    (package, ParsedPythonImportInfo(0, False))
                    for package in implicit_dependency_packages
                ),
                ParsedPythonAssetPaths(),
            ),
            resolve,
        ),
        **implicitly(),
    )

    spec_paths = [
        address.spec_path
        for result in resolved_dependencies.resolve_results.values()
        if result.status in (ImportOwnerStatus.unambiguous, ImportOwnerStatus.disambiguated)
        for address in result.address
    ]

    targets = await resolve_targets(
        **implicitly(
            RawSpecs.create(
                specs=[FileGlobSpec(f"{spec_path}/*.py") for spec_path in spec_paths],
                description_of_origin="Django implicit dependency detection",
            )
        )
    )

    return InferredDependencies(sorted(target.address for target in targets))


@rule
async def infer_django_dependencies(
    request: InferDjangoDependencies,
    python_setup: PythonSetup,
    django_apps: DjangoApps,
) -> InferredDependencies:
    source_field = request.field_set.source
    # NB: This doesn't consider https://docs.djangoproject.com/en/4.2/ref/settings/#std-setting-MIGRATION_MODULES
    path = PurePath(source_field.file_path)
    if path.match("migrations/*.py"):
        return await _django_migration_dependencies(request, python_setup, django_apps)
    elif path.match("apps.py"):
        return await _django_app_implicit_dependencies(request, python_setup, django_apps)
    else:
        return InferredDependencies([])


def rules():
    return (
        *collect_rules(),
        *pex.rules(),
        *dependency_inference.rules.rules(),
        UnionRule(InferDependenciesRequest, InferDjangoDependencies),
    )
