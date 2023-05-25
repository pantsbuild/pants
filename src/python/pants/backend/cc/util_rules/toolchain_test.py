# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import shutil

import pytest

from pants.backend.cc.dependency_inference.rules import rules as dep_inf_rules
from pants.backend.cc.subsystems.compiler import rules as compiler_rules
from pants.backend.cc.target_types import CCLanguage
from pants.backend.cc.target_types import rules as target_type_rules
from pants.backend.cc.util_rules.toolchain import CCProcess, CCToolchain, CCToolchainRequest
from pants.backend.cc.util_rules.toolchain import rules as toolchain_rules
from pants.core.util_rules import source_files
from pants.engine.process import ProcessResult
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *compiler_rules(),
            *dep_inf_rules(),
            *source_files.rules(),
            *target_type_rules(),
            *toolchain_rules(),
            QueryRule(CCToolchain, (CCToolchainRequest,)),
            QueryRule(ProcessResult, (CCProcess,)),
        ],
    )
    # Need to get the PATH so we can access system GCC or Clang
    # Need to set source roots in order to find include directories with partially qualified locations (e.g. foo/include/foo/bar.h)
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


@pytest.mark.skipif(
    not shutil.which("clang") and not shutil.which("gcc"), reason="Requires a system cc compiler"
)
def test_system_toolchain(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--cc-c-compiler-flags=-std=c89",
            "--cc-c-definitions=-DUNIT_TESTING",
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
    assert "-std=c89" in c_toolchain.compiler_flags
    assert "UNIT_TESTING" in c_toolchain.compiler_definitions

    rule_runner.set_options(
        [
            "--cc-cxx-compiler-flags=-std=c++20",
            "--cc-cxx-definitions=-DUNIT_TESTING",
        ],
        env_inherit={"PATH"},
    )
    cxx_toolchain = rule_runner.request(CCToolchain, [CCToolchainRequest(CCLanguage.CXX)])
    assert cxx_toolchain.compile_command[0].endswith(
        (
            "gcc++",
            "clang++",
        )
    )
    assert "-std=c++20" in cxx_toolchain.compiler_flags
    assert "UNIT_TESTING" in cxx_toolchain.compiler_definitions


@pytest.mark.no_error_if_skipped
@pytest.mark.skip(reason="This is a multi-gig file - skip until smaller alternatives can be found")
def test_downloaded_toolchain(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--cc-external-c-executable=gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-gcc",
            "--cc-external-cxx-executable=gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-g++",
            "--cc-external-version=10.3-2021.10",
            "--cc-external-known-versions=['10.3-2021.10|macos_x86_64|fb613dacb25149f140f73fe9ff6c380bb43328e6bf813473986e9127e2bc283b|158961466']",
            "--cc-external-url-template=https://developer.arm.com/-/media/Files/downloads/gnu-rm/{version}/gcc-arm-none-eabi-{version}-{platform}.tar.bz2",
            "--cc-external-url-platform-mapping={'macos_x86_64': 'mac'}",
            "--cc-external-c-compiler-flags=-std=c89",
            "--cc-external-c-definitions=-DUNIT_TESTING",
        ],
        env_inherit={"PATH"},
    )
    c_toolchain = rule_runner.request(CCToolchain, [CCToolchainRequest(CCLanguage.C)])
    assert c_toolchain.compiler.endswith("arm-none-eabi-gcc")
    assert "-std=c89" in c_toolchain.compiler_flags
    assert "UNIT_TESTING" in c_toolchain.compiler_definitions

    rule_runner.set_options(
        [
            "--cc-external-c-executable=gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-gcc",
            "--cc-external-cxx-executable=gcc-arm-none-eabi-10.3-2021.10/bin/arm-none-eabi-g++",
            "--cc-external-version=10.3-2021.10",
            "--cc-external-known-versions=['10.3-2021.10|macos_x86_64|fb613dacb25149f140f73fe9ff6c380bb43328e6bf813473986e9127e2bc283b|158961466']",
            "--cc-external-url-template=https://developer.arm.com/-/media/Files/downloads/gnu-rm/{version}/gcc-arm-none-eabi-{version}-{platform}.tar.bz2",
            "--cc-external-url-platform-mapping={'macos_x86_64': 'mac'}",
            "--cc-external-cxx-compiler-flags=-std=c++20",
            "--cc-external-cxx-definitions=-DUNIT_TESTING",
        ],
        env_inherit={"PATH"},
    )
    cxx_toolchain = rule_runner.request(CCToolchain, [CCToolchainRequest(CCLanguage.CXX)])
    assert cxx_toolchain.compiler.endswith("arm-none-eabi-g++")
    assert "-std=c++20" in cxx_toolchain.compiler_flags
    assert "UNIT_TESTING" in cxx_toolchain.compiler_definitions


@pytest.mark.skipif(
    not shutil.which("clang") and not shutil.which("gcc"), reason="Requires a system cc compiler"
)
def test_cc_process(rule_runner: RuleRunner) -> None:
    rule_runner.set_options([], env_inherit={"PATH"})
    result = rule_runner.request(
        ProcessResult,
        [
            CCProcess(
                args=("--version",),
                language=CCLanguage.C,
                description="Checking C compiler version",
            )
        ],
    )
    assert "gcc" in str(result.stdout) or "clang" in str(result.stdout)
