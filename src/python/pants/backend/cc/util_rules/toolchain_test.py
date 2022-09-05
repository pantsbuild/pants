# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.cc.dependency_inference.rules import rules as dep_inf_rules
from pants.backend.cc.target_types import CCLanguage, CCSourcesGeneratorTarget
from pants.backend.cc.target_types import rules as cc_target_type_rules
from pants.backend.cc.util_rules.compile import rules as cc_compile_rules
from pants.backend.cc.util_rules.toolchain import CCToolchain, CCToolchainRequest
from pants.backend.cc.util_rules.toolchain import rules as toolchain_rules
from pants.core.util_rules import source_files
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *cc_compile_rules(),
            *cc_target_type_rules(),
            *dep_inf_rules(),
            *source_files.rules(),
            *toolchain_rules(),
            QueryRule(CCToolchain, (CCToolchainRequest,)),
        ],
        target_types=[CCSourcesGeneratorTarget],
    )
    # Need to get the PATH so we can access system GCC or Clang
    # Need to set source roots in order to find include directories with partially qualified locations (e.g. foo/include/foo/bar.h)
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_system_toolchain(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--cc-c-compile-options=-std=c89",
            "--cc-c-defines=-DUNIT_TESTING",
        ],
        env_inherit={"PATH"},
    )
    c_toolchain = rule_runner.request(CCToolchain, [CCToolchainRequest(CCLanguage.C)])
    assert c_toolchain.compiler.endswith(
        (
            "gcc",
            "clang",
        )
    )
    assert "-std=c89" in c_toolchain.compile_flags
    assert "UNIT_TESTING" in c_toolchain.compile_defines

    rule_runner.set_options(
        [
            "--cc-cpp-compile-options=-std=c++20",
            "--cc-cpp-defines=-DUNIT_TESTING",
        ],
        env_inherit={"PATH"},
    )
    cpp_toolchain = rule_runner.request(CCToolchain, [CCToolchainRequest(CCLanguage.CPP)])
    assert cpp_toolchain.compile_command[0].endswith(
        (
            "gcc++",
            "clang++",
        )
    )
    assert "-std=c++20" in cpp_toolchain.compile_flags
    assert "UNIT_TESTING" in cpp_toolchain.compile_defines


def test_downloaded_toolchain(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--cc-external-c-executable=gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-gcc",
            "--cc-external-cpp-executable=gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-g++",
            "--cc-external-version=10.3-2021.10",
            "--cc-external-known-versions=['10.3-2021.10|macos_x86_64|fb613dacb25149f140f73fe9ff6c380bb43328e6bf813473986e9127e2bc283b|158961466']",
            "--cc-external-url-template=https://developer.arm.com/-/media/Files/downloads/gnu-rm/{version}/gcc-arm-none-eabi-{version}-{platform}.tar.bz2",
            "--cc-external-url-platform-mapping={'macos_x86_64': 'mac'}",
            "--cc-external-c-compile-options=-std=c89",
            "--cc-external-c-defines=-DUNIT_TESTING",
        ],
        env_inherit={"PATH"},
    )
    c_toolchain = rule_runner.request(CCToolchain, [CCToolchainRequest(CCLanguage.C)])
    assert c_toolchain.compiler.endswith("arm-none-eabi-gcc")
    assert "-std=c89" in c_toolchain.compile_flags
    assert "UNIT_TESTING" in c_toolchain.compile_defines

    rule_runner.set_options(
        [
            "--cc-external-c-executable=gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-gcc",
            "--cc-external-cpp-executable=gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-g++",
            "--cc-external-version=10.3-2021.10",
            "--cc-external-known-versions=['10.3-2021.10|macos_x86_64|fb613dacb25149f140f73fe9ff6c380bb43328e6bf813473986e9127e2bc283b|158961466']",
            "--cc-external-url-template=https://developer.arm.com/-/media/Files/downloads/gnu-rm/{version}/gcc-arm-none-eabi-{version}-{platform}.tar.bz2",
            "--cc-external-url-platform-mapping={'macos_x86_64': 'mac'}",
            "--cc-external-cpp-compile-options=-std=c++20",
            "--cc-external-cpp-defines=-DUNIT_TESTING",
        ],
        env_inherit={"PATH"},
    )
    cpp_toolchain = rule_runner.request(CCToolchain, [CCToolchainRequest(CCLanguage.CPP)])
    assert cpp_toolchain.compiler.endswith("arm-none-eabi-g++")
    assert "-std=c++20" in cpp_toolchain.compile_flags
    assert "UNIT_TESTING" in cpp_toolchain.compile_defines
