# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.backend.nfpm.fields.scripts import NfpmPackageScriptsField
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import FileLiteralSpec, RawSpecs
from pants.engine.addresses import Addresses
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies, Targets
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class NfpmPackageScriptsInferenceFieldSet(FieldSet):
    required_fields = (NfpmPackageScriptsField,)

    scripts: NfpmPackageScriptsField


class InferNfpmPackageScriptsDependencies(InferDependenciesRequest):
    infer_from = NfpmPackageScriptsInferenceFieldSet


@rule(
    desc=f"Infer dependencies based on nfpm `{NfpmPackageScriptsField.alias}` field.",
    level=LogLevel.DEBUG,
)
async def infer_nfpm_package_scripts_dependencies(
    request: InferNfpmPackageScriptsDependencies,
) -> InferredDependencies:
    scripts: NfpmPackageScriptsField = request.field_set.scripts
    scripts_paths = tuple(scripts.normalized_value.values())
    if not scripts_paths:
        return InferredDependencies(())

    resolved_scripts_addresses = await Get(
        Addresses,
        RawSpecs(
            file_literals=tuple(FileLiteralSpec(script_path) for script_path in scripts_paths),
            unmatched_glob_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="nfpm package scripts field dependency inference",
        ),
    )

    return InferredDependencies(resolved_scripts_addresses)


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferNfpmPackageScriptsDependencies),
    ]
