# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.nfpm.fields.version import NfpmVersionField, NfpmVersionReleaseField
from pants.backend.nfpm.target_types import target_types as nfpm_target_types
from pants.backend.nfpm.target_types_rules import rules as nfpm_target_types_rules
from pants.backend.nfpm.util_rules.inject_config import (
    InjectedNfpmPackageFields,
    InjectNfpmPackageFieldsRequest,
    NfpmPackageTargetWrapper,
)
from pants.backend.nfpm.util_rules.inject_config import rules as nfpm_inject_config_rules
from pants.engine.internals.native_engine import Address, Field
from pants.engine.rules import QueryRule, rule
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner

_PKG_NAME = "pkg"


class PluginInjectNfpmPackageFieldsRequest(InjectNfpmPackageFieldsRequest):
    @classmethod
    def is_applicable(cls, _) -> bool:
        return True


@rule
def inject_nfpm_package_fields_plugin(
    request: PluginInjectNfpmPackageFieldsRequest,
) -> InjectedNfpmPackageFields:
    address = request.target.address
    fields: list[Field] = [
        NfpmVersionField("9.8.7-dev+git", address),
        NfpmVersionReleaseField(6, address),
    ]
    return InjectedNfpmPackageFields(fields, address=address)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            *nfpm_target_types(),
        ],
        rules=[
            *nfpm_target_types_rules(),
            *nfpm_inject_config_rules(),
            inject_nfpm_package_fields_plugin,
            UnionRule(InjectNfpmPackageFieldsRequest, PluginInjectNfpmPackageFieldsRequest),
            QueryRule(InjectedNfpmPackageFields, (NfpmPackageTargetWrapper,)),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


@pytest.mark.parametrize(
    "packager",
    (
        "apk",
        "archlinux",
        "deb",
        "rpm",
    ),
)
def test_determine_injected_nfpm_package_fields(rule_runner: RuleRunner, packager: str) -> None:
    packager = "deb"
    rule_runner.write_files(
        {
            "BUILD": dedent(
                f"""
                nfpm_{packager}_package(
                    name="{_PKG_NAME}",
                    description="A {packager} package",
                    package_name="{_PKG_NAME}",
                    version="",  # the plugin should provide this
                    {"" if packager != "deb" else 'maintainer="Foo Bar <deb@example.com>",'}
                    dependencies=[],
                )
                """
            ),
        }
    )
    target = rule_runner.get_target(Address("", target_name=_PKG_NAME))
    result = rule_runner.request(InjectedNfpmPackageFields, [NfpmPackageTargetWrapper(target)])
    field_values = result.field_values
    assert len(field_values) == 2
    assert field_values[NfpmVersionField].value == "9.8.7-dev+git"
    assert field_values[NfpmVersionReleaseField].value == 6
