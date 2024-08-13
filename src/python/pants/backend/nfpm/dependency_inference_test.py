# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import PurePath
from textwrap import dedent

import pytest

from pants.backend.nfpm.dependency_inference import (
    InferNfpmPackageScriptsDependencies,
    NfpmPackageScriptsInferenceFieldSet,
)
from pants.backend.nfpm.dependency_inference import rules as nfpm_dep_rules
from pants.backend.nfpm.fields.apk import NfpmApkScriptsField
from pants.backend.nfpm.fields.deb import NfpmDebScriptsField
from pants.backend.nfpm.fields.rpm import NfpmRpmScriptsField
from pants.backend.nfpm.fields.scripts import NfpmPackageScriptsField
from pants.backend.nfpm.target_types import NfpmApkPackage, NfpmDebPackage, NfpmRpmPackage
from pants.core.target_types import FilesGeneratorTarget, FileTarget
from pants.core.target_types import rules as core_target_type_rules
from pants.engine.addresses import Address
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            FileTarget,
            FilesGeneratorTarget,
            NfpmApkPackage,
            NfpmDebPackage,
            NfpmRpmPackage,
        ],
        rules=[
            *core_target_type_rules(),
            *nfpm_dep_rules(),
            QueryRule(InferredDependencies, (InferNfpmPackageScriptsDependencies,)),
        ],
    )
    return rule_runner


_PKG_NAME = "pkg"
_PKG_VERSION = "3.2.1"


@pytest.mark.parametrize(
    "packager,scripts_field_type",
    (
        ("apk", NfpmApkScriptsField),
        ("deb", NfpmDebScriptsField),
        ("rpm", NfpmRpmScriptsField),
    ),
)
def test_infer_nfpm_package_scripts_dependencies(
    rule_runner: RuleRunner, packager: str, scripts_field_type: type[NfpmPackageScriptsField]
) -> None:
    scripts_types = tuple(script_type for script_type in scripts_field_type.nfpm_aliases)
    scripts = {script_type: f"scripts/{script_type}.sh" for script_type in scripts_types}
    scripts_paths = tuple(scripts.values())
    relative_scripts_paths = [
        PurePath(path).relative_to("scripts").as_posix() for path in scripts_paths
    ]
    rule_runner.write_files(
        {
            "BUILD": dedent(
                f"""
                nfpm_{packager}_package(
                    name="{_PKG_NAME}",
                    package_name="{_PKG_NAME}",
                    version="{_PKG_VERSION}",
                    {'' if packager != 'deb' else 'maintainer="Foo Bar <deb@example.com>",'}
                    scripts={scripts},
                )
                """
            ),
            "scripts/BUILD": dedent(
                f"""
                files(
                    name="scripts",
                    sources={relative_scripts_paths},
                )
                """
            ),
            **{path: "" for path in scripts_paths},
        }
    )

    def run_dep_inference(address: Address) -> InferredDependencies:
        target = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies,
            [
                InferNfpmPackageScriptsDependencies(
                    NfpmPackageScriptsInferenceFieldSet.create(target)
                )
            ],
        )

    assert run_dep_inference(
        Address("", target_name=_PKG_NAME),
    ) == InferredDependencies(
        [
            Address("scripts", relative_file_path=f"{script_type}.sh")
            for script_type in scripts_types
        ],
    )
