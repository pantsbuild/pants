# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from copy import deepcopy
from pathlib import PurePath
from typing import Final, Iterable

import libcst as cst
import pytest

from pants.goal.migrate_call_by_name import Replacement, fix_implicitly_usage
from pants.util.cstutil import make_importfrom_attr as import_attr

OLD_FUNC_NAME: Final[str] = "hello"
NEW_FUNC_NAME: Final[str] = "goodbye"

IMPORT_ATTR_ENGINE: Final[cst.Attribute | cst.Name] = import_attr("pants.engine.rules")
IMPORT_ATTR_GREETING: Final[cst.Attribute | cst.Name] = import_attr("pants.greeting")

DEFAULT_REPLACEMENT: Final[Replacement] = Replacement(
    filename=PurePath("pants/foo/bar.py"),
    module="pants.foo.bar",
    current_source=cst.Call(func=cst.Name(OLD_FUNC_NAME)),
    new_source=cst.Call(func=cst.Name(NEW_FUNC_NAME)),
    additional_imports=[
        cst.ImportFrom(module=IMPORT_ATTR_ENGINE, names=[cst.ImportAlias(cst.Name("implicitly"))]),
        cst.ImportFrom(
            module=IMPORT_ATTR_GREETING, names=[cst.ImportAlias(cst.Name(NEW_FUNC_NAME))]
        ),
    ],
)


def test_replacement_sanitizes_circular_imports():
    replacement = deepcopy(DEFAULT_REPLACEMENT)
    replacement.additional_imports.append(
        cst.ImportFrom(
            module=import_attr("pants.foo.bar"), names=[cst.ImportAlias(cst.Name("baz"))]
        )
    )

    sanitized_imports = replacement.sanitized_imports()
    assert len(sanitized_imports) == 2
    assert sanitized_imports[0].module is not None
    assert sanitized_imports[0].module.deep_equals(IMPORT_ATTR_ENGINE)
    assert sanitized_imports[1].module is not None
    assert sanitized_imports[1].module.deep_equals(IMPORT_ATTR_GREETING)


def test_replacement_sanitize_noop():
    replacement = deepcopy(DEFAULT_REPLACEMENT)

    replacement.sanitize(unavailable_names=set())
    assert str(replacement) == str(DEFAULT_REPLACEMENT)

    replacement.sanitize(unavailable_names={"fake_name", "irrelevant_name"})
    assert str(replacement) == str(DEFAULT_REPLACEMENT)


def test_replacement_sanitize_noop_in_same_module():
    replacement = deepcopy(DEFAULT_REPLACEMENT)
    replacement.additional_imports = []
    replacement.sanitize(unavailable_names={NEW_FUNC_NAME})

    unsanitized_replacement = deepcopy(DEFAULT_REPLACEMENT)
    unsanitized_replacement.additional_imports = []
    assert str(replacement) == str(unsanitized_replacement)


def test_replacement_sanitizes_shadowed_code():
    replacement = deepcopy(DEFAULT_REPLACEMENT)

    replacement.sanitize(unavailable_names={NEW_FUNC_NAME})
    assert str(replacement) != str(DEFAULT_REPLACEMENT)

    assert isinstance(replacement.new_source.func, cst.Name)
    assert replacement.new_source.func.value == f"{NEW_FUNC_NAME}_get"

    imp = replacement.additional_imports[1]
    assert imp.module is not None
    assert imp.module.deep_equals(IMPORT_ATTR_GREETING)

    assert isinstance(imp.names, Iterable)
    assert imp.names[0].name.deep_equals(cst.Name(NEW_FUNC_NAME))
    assert imp.names[0].asname is not None
    assert imp.names[0].asname.deep_equals(cst.AsName(cst.Name(f"{NEW_FUNC_NAME}_get")))


def test_fix_implicitly_noop():
    call = _parse_call("no_op()")
    target_func = _parse_funcdef("async def no_op(): ...")
    new_call = fix_implicitly_usage(call, target_func)
    assert new_call.deep_equals(call)
    assert new_call.deep_equals(_parse_call("no_op()"))


@pytest.mark.parametrize(
    "source, target, expected",
    [
        (
            "some_random_func(**implicitly())",
            "async def unrelated_func(): ...",
            "some_random_func(**implicitly())",
        ),
        (
            "multi_arg_call(arg1, arg2, **implicitly())",
            "async def multi_arg_call(arg1: str, arg2: str): ...",
            "multi_arg_call(arg1, arg2, **implicitly())",
        ),
        (
            "create_archive(CreateArchive(EMPTY_SNAPSHOT), **implicitly())",
            "async def create_archive(request: CreateArchive, system_binaries_environment: SystemBinariesSubsystem.EnvironmentAware) -> Digest: ...",
            "create_archive(CreateArchive(EMPTY_SNAPSHOT), **implicitly())",
        ),
    ],
)
def test_fix_implicitly_keeps_required(source: str, target: str, expected: str):
    call = _parse_call(source)
    target_func = _parse_funcdef(target)
    new_call = fix_implicitly_usage(call, target_func)

    dummy_module = cst.parse_module("")
    assert new_call.deep_equals(
        call
    ), f"Expected {dummy_module.code_for_node(new_call)} to equal {dummy_module.code_for_node(call)}"
    assert new_call.deep_equals(
        _parse_call(expected)
    ), f"Expected {dummy_module.code_for_node(new_call)} to equal {expected}"


@pytest.mark.parametrize(
    "source, target, expected",
    [
        (
            "find_all_targets(**implicitly())",
            "async def find_all_targets() -> AllTargets: ...",
            "find_all_targets()",
        ),
        (
            "digest_to_snapshot(Digest('a', 1), **implicitly())",
            "async def digest_to_snapshot(digest: Digest) -> Snapshot: ...",
            "digest_to_snapshot(Digest('a', 1))",
        ),
        (
            "create_pex(**implicitly({clangformat.to_pex_request(): PexRequest}))",
            "async def create_pex(request: PexRequest) -> Pex: ...",
            "create_pex(clangformat.to_pex_request())",
        ),
    ],
)
def test_fix_implicitly_usage_removes_unneeded(source: str, target: str, expected: str):
    call = _parse_call(source)
    target_func = _parse_funcdef(target)
    new_call = fix_implicitly_usage(call, target_func)

    dummy_module = cst.parse_module("")
    assert not new_call.deep_equals(
        call
    ), f"Expected {dummy_module.code_for_node(new_call)} to not equal {dummy_module.code_for_node(call)}"
    assert new_call.deep_equals(
        _parse_call(expected)
    ), f"Expected {dummy_module.code_for_node(new_call)} to equal {expected}"


@pytest.mark.parametrize(
    "source, target, expected",
    [
        (
            "create_venv_pex(**implicitly({clangformat.to_pex_request(): PexRequest}))",
            "async def create_venv_pex(request: VenvPexRequest, bash: BashBinary, pex_environment: PexEnvironment) -> VenvPex: ...",
            "create_venv_pex(**implicitly(clangformat.to_pex_request()))",
        ),
        (
            "digest_to_snapshot(DigestSubset(config_files.snapshot.digest, PathGlobs([config_file])), **implicitly())",
            "async def digest_to_snapshot(digest: Digest) -> Snapshot: ...",
            "digest_to_snapshot(**implicitly(DigestSubset(config_files.snapshot.digest, PathGlobs([config_file]))))",
        ),
        (
            "process_request_to_process_result(VenvPexProcess(arg1, arg2, arg3), **implicitly())",
            "async def process_request_to_process_result(process: Process, process_execution_environment: ProcessExecutionEnvironment) -> FallibleProcessResult: ...",
            "process_request_to_process_result(**implicitly(VenvPexProcess(arg1, arg2, arg3)))",
        ),
    ],
)
def test_fix_implicitly_usage_modification(source: str, target: str, expected: str):
    call = _parse_call(source)
    target_func = _parse_funcdef(target)
    new_call = fix_implicitly_usage(call, target_func)

    dummy_module = cst.parse_module("")
    assert new_call.deep_equals(
        _parse_call(expected)
    ), f"Expected {dummy_module.code_for_node(new_call)} to equal {expected}"


def _parse_call(source: str) -> cst.Call:
    return cst.ensure_type(cst.parse_expression(source), cst.Call)


def _parse_funcdef(source: str) -> cst.FunctionDef:
    return cst.ensure_type(cst.parse_statement(source), cst.FunctionDef)
