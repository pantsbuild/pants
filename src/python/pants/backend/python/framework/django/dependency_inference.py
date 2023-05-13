# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from pathlib import PurePath

from pants.backend.python.dependency_inference.parse_python_dependencies import (
    ParsedPythonAssetPaths,
    ParsedPythonDependencies,
    ParsedPythonImportInfo,
    ParsedPythonImports,
)
from pants.backend.python.dependency_inference.rules import (
    ImportOwnerStatus,
    PythonImportDependenciesInferenceFieldSet,
    ResolvedParsedPythonDependencies,
    ResolvedParsedPythonDependenciesRequest,
)
from pants.backend.python.framework.django.detect_apps import DjangoApps
from pants.backend.python.subsystems.setup import PythonSetup
from pants.core.util_rules.adhoc_binaries import PythonBuildStandaloneBinary
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.resources import read_resource


class InferDjangoDependencies(InferDependenciesRequest):
    infer_from = PythonImportDependenciesInferenceFieldSet


_visitor_resource = "scripts/dependency_visitor.py"


@rule
async def django_parser_script(
    request: InferDjangoDependencies,
    python_setup: PythonSetup,
    django_apps: DjangoApps,
    python: PythonBuildStandaloneBinary,
) -> InferredDependencies:
    source_field = request.field_set.source
    # NB: This doesn't consider https://docs.djangoproject.com/en/4.2/ref/settings/#std-setting-MIGRATION_MODULES
    if not PurePath(source_field.file_path).match("migrations/*.py"):
        return InferredDependencies([])
    # @TODO: Py 2.7 warn?

    stripped_sources = await Get(
        StrippedSourceFiles, SourceFilesRequest([request.field_set.source])
    )
    assert len(stripped_sources.snapshot.files) == 1

    file_content = FileContent("script/__visitor.py", read_resource(__name__, _visitor_resource))
    visitor_digest = await Get(Digest, CreateDigest([file_content]))
    input_digest = await Get(Digest, MergeDigests([stripped_sources.snapshot.digest, visitor_digest]))
    # @TODO: Have to use Py Executable, womp womp
    process_result = await Get(
        ProcessResult,
        Process(
            argv=[
                python.path,
                file_content.path,
                stripped_sources.snapshot.files[0],
            ],
            input_digest=input_digest,
            immutable_input_digests=python.immutable_input_digests,
            description=f"Determine Django app dependencies for {request.field_set.address}",
            level=LogLevel.DEBUG,
        ),
    )
    # See in script for where we explicitly encoded as utf8. Even though utf8 is the
    # default for decode(), we make that explicit here for emphasis.
    process_output = process_result.stdout or "{}"
    modules = [
        "{}.migrations.{}".format(django_apps.label_to_name[label], migration)
        for label, migration in json.loads(process_output)
        if label in django_apps.label_to_name
    ]
    resolve = request.field_set.resolve.normalized_value(python_setup)

    resolved_dependencies = await Get(
        ResolvedParsedPythonDependencies,
        ResolvedParsedPythonDependenciesRequest(
            request.field_set,
            ParsedPythonDependencies(
                ParsedPythonImports(
                    (module, ParsedPythonImportInfo(0, True)) for module in modules
                ),
                ParsedPythonAssetPaths(),
            ),
            resolve,
        ),
    )

    return InferredDependencies(
        sorted(
            address
            for result in resolved_dependencies.resolve_results.values()
            if result.status in (ImportOwnerStatus.unambiguous, ImportOwnerStatus.disambiguated)
            for address in result.address
        )
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferDjangoDependencies),
    ]
