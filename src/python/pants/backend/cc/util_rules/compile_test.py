# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.cc.dependency_inference.rules import rules as dep_inf_rules
from pants.backend.cc.target_types import CCFieldSet, CCSourcesGeneratorTarget
from pants.backend.cc.target_types import rules as cc_target_type_rules
from pants.backend.cc.util_rules import toolchain
from pants.backend.cc.util_rules.compile import CompileCCSourceRequest, FallibleCompiledCCObject
from pants.backend.cc.util_rules.compile import rules as cc_compile_rules
from pants.core.util_rules import source_files
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.addresses import Address
from pants.engine.process import Process
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *archive_rules(),
            *cc_compile_rules(),
            *cc_target_type_rules(),
            *dep_inf_rules(),
            *source_files.rules(),
            *toolchain.rules(),
            QueryRule(FallibleCompiledCCObject, (CompileCCSourceRequest,)),
            QueryRule(Process, (toolchain.CCProcess,)),
        ],
        target_types=[CCSourcesGeneratorTarget],
    )
    # Need to get the PATH so we can access system GCC or Clang
    # Need to set source roots in order to find include directories with partially qualified locations (e.g. foo/include/foo/bar.h)
    rule_runner.set_options(["--source-marker-filenames=BUILD"], env_inherit={"PATH"})
    return rule_runner


BAD_FILE_C = """\
    int main()
    {
        printf("Hello, world!");
        return 0;
    }
    """

GOOD_FILE_C = """\
    #include <stdio.h>

    int main()
    {
        printf("Hello, world!");
        return 0;
    }
    """

BAD_FILE_CPP = """\
    int main()
    {
        std::cout << "Hello, world!" << std::endl;
        return 0;
    }
    """

GOOD_FILE_CPP = """\
    #include <iostream>

    int main()
    {
        std::cout << "Hello, world!" << std::endl;
        return 0;
    }
    """

FILE_INFERENCE_MAIN = """\
    #include "foo.h"
    #include <iostream>

    int main()
    {
        std::cout << "Hello, world!" << std::endl;
        return bar();
    }
    """

FILE_INFERENCE_SOURCE_ROOT = """\
    #include "foobar/foo.h"
    #include <iostream>

    int main()
    {
        std::cout << "Hello, world!" << std::endl;
        return bar();
    }
    """

FILE_INFERENCE_HEADER = """\
    int bar() {
        return 0;
    }
    """


def run_compile(
    rule_runner: RuleRunner,
    target: Target,
) -> FallibleCompiledCCObject:
    return rule_runner.request(
        FallibleCompiledCCObject, [CompileCCSourceRequest(CCFieldSet.create(target))]
    )


def test_compile_pass_c(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"main.c": GOOD_FILE_C, "BUILD": "cc_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="main.c"))
    compile_result = run_compile(
        rule_runner,
        tgt,
    )
    assert compile_result.process_result.exit_code == 0


def test_compile_fail_c(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"main.c": BAD_FILE_C, "BUILD": "cc_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="main.c"))
    compile_result = run_compile(
        rule_runner,
        tgt,
    )
    assert compile_result.process_result.exit_code == 1
    # TODO: This error changes depending on compiler
    assert "error: implicitly declaring library function" in str(
        compile_result.process_result.stderr
    )


def test_compile_pass_cpp(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"main.cpp": GOOD_FILE_CPP, "BUILD": "cc_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="main.cpp"))
    compile_result = run_compile(
        rule_runner,
        tgt,
    )
    assert compile_result.process_result.exit_code == 0


def test_compile_fail_cpp(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"main.cpp": BAD_FILE_CPP, "BUILD": "cc_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="main.cpp"))
    compile_result = run_compile(
        rule_runner,
        tgt,
    )
    assert compile_result.process_result.exit_code == 1
    # TODO: This error changes depending on compiler
    assert "error: use of undeclared identifier" in str(compile_result.process_result.stderr)


def test_compile_pass_with_inference(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "main.cpp": FILE_INFERENCE_MAIN,
            "foo.h": FILE_INFERENCE_HEADER,
            "BUILD": "cc_sources(name='t')",
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="main.cpp"))
    compile_result = run_compile(
        rule_runner,
        tgt,
    )
    assert compile_result.process_result.exit_code == 0


def test_compile_fail_with_inference(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"main.cpp": FILE_INFERENCE_MAIN, "BUILD": "cc_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="main.cpp"))
    compile_result = run_compile(
        rule_runner,
        tgt,
    )
    assert compile_result.process_result.exit_code == 1


# TODO: Why do I need to nest this under another folder just for this to work correctly?
# Refer to source root checking in dependency inference
def test_compile_pass_with_source_root_inference(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "example/src/main.cpp": FILE_INFERENCE_SOURCE_ROOT,
            "example/include/foobar/foo.h": FILE_INFERENCE_HEADER,
            "example/src/BUILD": "cc_sources(name='t')",
            "example/include/foobar/BUILD": "cc_sources(name='headers')",
            "example/BUILD": "",
        }
    )
    tgt = rule_runner.get_target(
        Address("example/src", target_name="t", relative_file_path="main.cpp")
    )
    compile_result = run_compile(
        rule_runner,
        tgt,
    )
    print(compile_result.process_result.stderr)
    assert compile_result.process_result.exit_code == 0
