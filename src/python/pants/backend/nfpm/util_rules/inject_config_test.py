# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Any

import pytest

from pants.backend.nfpm.fields.all import NfpmPlatformField
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


class PluginInjectFieldsRequest(InjectNfpmPackageFieldsRequest):
    @classmethod
    def is_applicable(cls, _) -> bool:
        return True


@rule
async def inject_nfpm_package_fields_plugin(
    request: PluginInjectFieldsRequest,
) -> InjectedNfpmPackageFields:
    address = request.target.address
    # preserve fields from earlier rules in chain
    fields: list[Field] = list(request.injected_fields.values())
    if NfpmVersionField not in request.injected_fields:
        fields.extend(
            [
                NfpmVersionField("9.8.7-dev+git", address),
                NfpmVersionReleaseField(6, address),
            ]
        )
    return InjectedNfpmPackageFields(fields, address=address)


class SubclassPluginInjectFieldsRequest(PluginInjectFieldsRequest):
    pass


@rule
async def inject_nfpm_package_fields_subclass(
    request: SubclassPluginInjectFieldsRequest,
) -> InjectedNfpmPackageFields:
    address = request.target.address
    # preserve fields from earlier rules in chain
    fields: list[Field] = list(request.injected_fields.values())
    if not fields or NfpmVersionReleaseField in request.injected_fields:
        release = 0
        if NfpmVersionReleaseField in request.injected_fields:
            old_release = request.injected_fields[NfpmVersionReleaseField].value
            assert old_release is not None
            release = 10 + old_release
        fields.append(NfpmVersionReleaseField(release, address))
    return InjectedNfpmPackageFields(fields, address=address)


class HighPriorityInjectFieldsRequest(InjectNfpmPackageFieldsRequest):
    priority = 100

    @classmethod
    def is_applicable(cls, _) -> bool:
        return True

    @classmethod
    def lt_fallback(cls, other: Any) -> bool:
        return False


@rule
async def inject_nfpm_package_fields_high_priority(
    request: HighPriorityInjectFieldsRequest,
) -> InjectedNfpmPackageFields:
    address = request.target.address
    # preserve fields from earlier rules in chain
    fields: list[Field] = list(request.injected_fields.values())
    if not fields or NfpmVersionField not in request.injected_fields:
        fields.extend(
            [
                NfpmVersionField("9.9.9-dev+git", address),
                NfpmVersionReleaseField(9, address),
            ]
        )
    # The high priority implementation that wants to force Platform to always be "foobar"
    # even if another rule injected NfpmPlatformField
    fields.append(NfpmPlatformField("foobar", address))
    return InjectedNfpmPackageFields(fields, address=address)


@pytest.mark.parametrize(
    "a,b,expected_lt",
    (
        # HighPriority* > SubclassPlugin* > Plugin*
        (HighPriorityInjectFieldsRequest, SubclassPluginInjectFieldsRequest, False),
        (HighPriorityInjectFieldsRequest, PluginInjectFieldsRequest, False),
        (SubclassPluginInjectFieldsRequest, HighPriorityInjectFieldsRequest, True),
        (SubclassPluginInjectFieldsRequest, PluginInjectFieldsRequest, False),
        (PluginInjectFieldsRequest, HighPriorityInjectFieldsRequest, True),
        (PluginInjectFieldsRequest, SubclassPluginInjectFieldsRequest, True),
        # self is equal which is not less than
        (HighPriorityInjectFieldsRequest, HighPriorityInjectFieldsRequest, False),
    ),
)
def test_nfpm_package_fields_request_class_sort(a: Any, b: Any, expected_lt):
    ret = a < b
    assert ret == expected_lt, f"a.priority={a.priority} b.priority={b.priority}"


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
            inject_nfpm_package_fields_subclass,
            inject_nfpm_package_fields_high_priority,
            UnionRule(InjectNfpmPackageFieldsRequest, PluginInjectFieldsRequest),
            UnionRule(InjectNfpmPackageFieldsRequest, SubclassPluginInjectFieldsRequest),
            UnionRule(InjectNfpmPackageFieldsRequest, HighPriorityInjectFieldsRequest),
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
    assert len(field_values) == 3
    assert field_values[NfpmVersionField].value == "9.8.7-dev+git"  # (Plugin*)
    assert field_values[NfpmVersionReleaseField].value == 16  # 6 (Plugin*) + 10 (SubclassPlugin*)
    assert field_values[NfpmPlatformField].value == "foobar"  # (HighPriority*)
