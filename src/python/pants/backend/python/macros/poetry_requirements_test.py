# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Any, Dict, Iterable

import pytest
from packaging.version import Version
from pkg_resources import Requirement

from pants.backend.python.macros.poetry_requirements import (
    PoetryRequirements,
    get_max_caret,
    get_max_tilde,
    handle_dict_attr,
    parse_pyproject_toml,
    parse_single_dependency,
    parse_str_version,
)
from pants.backend.python.target_types import PythonRequirementLibrary, PythonRequirementsFile
from pants.base.specs import AddressSpecs, DescendantAddresses, FilesystemSpecs, Specs
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import Targets
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.mark.parametrize(
    "test, exp",
    [
        ("1.0.0-rc0", "2.0.0"),
        ("1.2.3.dev0", "2.0.0"),
        ("1.2.3-dev0", "2.0.0"),
        ("1.2.3dev0", "2.0.0"),
        ("1.2.3", "2.0.0"),
        ("1.2", "2.0.0"),
        ("1", "2.0.0"),
        ("0.2.3", "0.3.0"),
        ("0.0.3", "0.0.4"),
        ("0.0", "0.1.0"),
        ("0", "1.0.0"),
    ],
)
def test_caret(test, exp) -> None:
    version = Version(test)
    assert get_max_caret(version) == exp


@pytest.mark.parametrize(
    "test, exp",
    [
        ("1.2.3", "1.3.0"),
        ("1.2", "1.3.0"),
        ("1", "2.0.0"),
        ("0", "1.0.0"),
        ("1.2.3.rc1", "1.3.0"),
        ("1.2.3rc1", "1.3.0"),
        ("1.2.3-rc1", "1.3.0"),
    ],
)
def test_max_tilde(test, exp) -> None:
    version = Version(test)
    assert get_max_tilde(version) == exp


@pytest.mark.parametrize(
    "test, exp",
    [
        ("~1.0.0rc0", ">=1.0.0rc0,<1.1.0"),
        ("^1.0.0rc0", ">=1.0.0rc0,<2.0.0"),
        ("~1.2.3", ">=1.2.3,<1.3.0"),
        ("^1.2.3", ">=1.2.3,<2.0.0"),
        ("~=1.2.3", "~=1.2.3"),
        ("1.2.3", "==1.2.3"),
        (">1.2.3", ">1.2.3"),
        ("~1.2, !=1.2.10", ">=1.2,<1.3.0,!=1.2.10"),
    ],
)
def test_handle_str(test, exp) -> None:
    assert parse_str_version("foo", test, "") == f"foo {exp}"


def test_handle_git() -> None:
    def assert_git(extra_opts: Dict[str, str], suffix: str) -> None:
        attr = {"git": "https://github.com/requests/requests.git", **extra_opts}
        assert (
            handle_dict_attr("requests", attr, "")
            == f"requests @ git+https://github.com/requests/requests.git{suffix}"
        )

    assert_git({}, "")
    assert_git({"branch": "main"}, "@main")
    assert_git({"tag": "v1.1.1"}, "@v1.1.1")
    assert_git({"rev": "1a2b3c4d"}, "#1a2b3c4d")


def test_handle_path_arg() -> None:
    attr = {"path": "../../my_py_proj.whl"}
    assert handle_dict_attr("my_py_proj", attr, "") == "my_py_proj @ file://../../my_py_proj.whl"


def test_handle_url_arg() -> None:
    attr = {"url": "https://my-site.com/mydep.whl"}
    assert handle_dict_attr("my_py_proj", attr, "") == "my_py_proj @ https://my-site.com/mydep.whl"


def test_version_only() -> None:
    attr = {"version": "1.2.3"}
    assert handle_dict_attr("foo", attr, "") == "foo ==1.2.3"


def test_py_constraints() -> None:
    def assert_py_constraints(py_req: str, suffix: str) -> None:
        attr = {"version": "1.2.3", "python": py_req}
        assert handle_dict_attr("foo", attr, "") == f"foo ==1.2.3;{suffix}"

    assert_py_constraints("3.6", "python_version == '3.6'")
    assert_py_constraints("3.6 || 3.7", "(python_version == '3.6') or (python_version == '3.7')")
    assert_py_constraints(">3.6,!=3.7", "python_version > '3.6' and python_version != '3.7'")
    assert_py_constraints(
        ">3.6 || 3.5,3.4",
        "(python_version > '3.6') or (python_version == '3.5' and python_version == '3.4')",
    )
    assert_py_constraints(
        "~3.6 || ^3.7",
        "(python_version >= '3.6' and python_version< '3.7') or (python_version >= '3.7' and python_version< '4.0')",
    )


def test_multi_version_const() -> None:
    lst_attr = [{"version": "1.2.3", "python": "3.6"}, {"version": "1.2.4", "python": "3.7"}]
    retval = parse_single_dependency("foo", lst_attr, "")
    actual_reqs = (
        Requirement.parse("foo ==1.2.3; python_version == '3.6'"),
        Requirement.parse("foo ==1.2.4; python_version == '3.7'"),
    )
    assert retval == actual_reqs


def test_extended_form() -> None:
    toml_black_str = """
    [tool.poetry.dependencies]
    [tool.poetry.dependencies.black]
    version = "19.10b0"
    python = "3.6"
    markers = "platform_python_implementation == 'CPython'"
    [tool.poetry.dev-dependencies]
    """
    retval = parse_pyproject_toml(toml_black_str, "/path/to/file")
    actual_req = {
        Requirement.parse(
            'black==19.10b0; platform_python_implementation == "CPython" and python_version == "3.6"'
        )
    }
    assert retval == actual_req


def test_parse_multi_reqs() -> None:
    toml_str = """[tool.poetry]
    name = "poetry_tinker"
    version = "0.1.0"
    description = ""
    authors = ["Liam Wilson <lswilson0709@gmail.com>"]

    [tool.poetry.dependencies]
    python = "^3.8"
    junk = {url = "https://github.com/myrepo/junk.whl"}
    poetry = {git = "https://github.com/python-poetry/poetry.git", tag = "v1.1.1"}
    requests = {extras = ["security"], version = "^2.25.1", python = ">2.7"}
    foo = [{version = ">=1.9", python = "^2.7"},{version = "^2.0", python = "3.4 || 3.5"}]

    [tool.poetry.dependencies.black]
    version = "19.10b0"
    python = "3.6"
    markers = "platform_python_implementation == 'CPython'"

    [tool.poetry.dev-dependencies]
    isort = ">=5.5.1,<5.6"

    [build-system]
    requires = ["poetry-core>=1.0.0"]
    build-backend = "poetry.core.masonry.api"
    """
    retval = parse_pyproject_toml(toml_str, "/path/to/file")
    actual_reqs = {
        Requirement.parse("junk@ https://github.com/myrepo/junk.whl"),
        Requirement.parse("poetry@ git+https://github.com/python-poetry/poetry.git@v1.1.1"),
        Requirement.parse('requests<3.0.0,>=2.25.1; python_version > "2.7"'),
        Requirement.parse('foo>=1.9; python_version >= "2.7" and python_version < "3.0"'),
        Requirement.parse('foo<3.0.0,>=2.0; python_version == "3.4" or python_version == "3.5"'),
        Requirement.parse(
            'black==19.10b0; platform_python_implementation == "CPython" and python_version == "3.6"'
        ),
        Requirement.parse("isort<5.6,>=5.5.1"),
    }
    assert retval == actual_reqs


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[QueryRule(Targets, (Specs,))],
        target_types=[PythonRequirementLibrary, PythonRequirementsFile],
        context_aware_object_factories={"poetry_requirements": PoetryRequirements},
    )


def assert_poetry_requirements(
    rule_runner: RuleRunner,
    build_file_entry: str,
    pyproject_toml: str,
    *,
    expected_file_dep: PythonRequirementsFile,
    expected_targets: Iterable[PythonRequirementLibrary],
    pyproject_toml_relpath: str = "pyproject.toml",
) -> None:
    rule_runner.add_to_build_file("", f"{build_file_entry}\n")
    rule_runner.create_file(pyproject_toml_relpath, pyproject_toml)
    targets = rule_runner.request(
        Targets,
        [Specs(AddressSpecs([DescendantAddresses("")]), FilesystemSpecs([]))],
    )
    assert {expected_file_dep, *expected_targets} == set(targets)


def test_pyproject_toml(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new python_requirement_library for each entry in a
    pyproject.toml file.

    Note that this just ensures proper targets are created; see prior tests for specific parsing
    edge cases.
    """
    assert_poetry_requirements(
        rule_runner,
        dedent(
            """\
            poetry_requirements(
                module_mapping={'ansicolors': ['colors']},
                type_stubs_module_mapping={'Django-types': ['django']},
            )
            """
        ),
        dedent(
            """\
            [tool.poetry.dependencies]
            Django = {version = "3.2", python = "3"}
            Django-types = "2"
            Un-Normalized-PROJECT = "1.0.0"
            [tool.poetry.dev-dependencies]
            ansicolors = ">=1.18.0"
            """
        ),
        expected_file_dep=PythonRequirementsFile(
            {"sources": ["pyproject.toml"]},
            address=Address("", target_name="pyproject.toml"),
        ),
        expected_targets=[
            PythonRequirementLibrary(
                {
                    "dependencies": [":pyproject.toml"],
                    "requirements": [Requirement.parse("ansicolors>=1.18.0")],
                    "module_mapping": {"ansicolors": ["colors"]},
                },
                address=Address("", target_name="ansicolors"),
            ),
            PythonRequirementLibrary(
                {
                    "dependencies": [":pyproject.toml"],
                    "requirements": [Requirement.parse("Django==3.2 ; python_version == '3'")],
                },
                address=Address("", target_name="Django"),
            ),
            PythonRequirementLibrary(
                {
                    "dependencies": [":pyproject.toml"],
                    "requirements": [Requirement.parse("Django-types==2")],
                    "type_stubs_module_mapping": {"Django-types": ["django"]},
                },
                address=Address("", target_name="Django-types"),
            ),
            PythonRequirementLibrary(
                {
                    "dependencies": [":pyproject.toml"],
                    "requirements": [Requirement.parse("Un_Normalized_PROJECT == 1.0.0")],
                },
                address=Address("", target_name="Un-Normalized-PROJECT"),
            ),
        ],
    )


def test_relpath_override(rule_runner: RuleRunner) -> None:
    assert_poetry_requirements(
        rule_runner,
        "poetry_requirements(pyproject_toml_relpath='subdir/pyproject.toml')",
        dedent(
            """\
            [tool.poetry.dependencies]
            ansicolors = ">=1.18.0"
            [tool.poetry.dev-dependencies]
            """
        ),
        pyproject_toml_relpath="subdir/pyproject.toml",
        expected_file_dep=PythonRequirementsFile(
            {"sources": ["subdir/pyproject.toml"]},
            address=Address("", target_name="subdir_pyproject.toml"),
        ),
        expected_targets=[
            PythonRequirementLibrary(
                {
                    "dependencies": [":subdir_pyproject.toml"],
                    "requirements": [Requirement.parse("ansicolors>=1.18.0")],
                },
                address=Address("", target_name="ansicolors"),
            ),
        ],
    )


def test_non_pep440_error(rule_runner: RuleRunner, caplog: Any) -> None:
    with pytest.raises(ExecutionError) as exc:
        assert_poetry_requirements(
            rule_runner,
            "poetry_requirements()",
            """
            [tool.poetry.dependencies]
            foo = "~r62b"
            [tool.poetry.dev-dependencies]
            """,
            expected_file_dep=PythonRequirementsFile(
                {"sources": ["pyproject.toml"]},
                address=Address("", target_name="pyproject.toml"),
            ),
            expected_targets=[],
        )
    assert 'Failed to parse requirement foo = "~r62b" in pyproject.toml' in str(exc.value)


def test_no_req_defined_warning(rule_runner: RuleRunner, caplog: Any) -> None:
    assert_poetry_requirements(
        rule_runner,
        "poetry_requirements()",
        """
        [tool.poetry.dependencies]
        [tool.poetry.dev-dependencies]
        """,
        expected_file_dep=PythonRequirementsFile(
            {"sources": ["pyproject.toml"]},
            address=Address("", target_name="pyproject.toml"),
        ),
        expected_targets=[],
    )
    assert "No requirements defined" in caplog.text


def test_bad_dict_format(rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError) as exc:
        assert_poetry_requirements(
            rule_runner,
            "poetry_requirements()",
            """
            [tool.poetry.dependencies]
            foo = {bad_req = "test"}
            [tool.poetry.dev-dependencies]
            """,
            expected_file_dep=PythonRequirementsFile(
                {"sources": ["pyproject.toml"]},
                address=Address("", target_name="pyproject.toml"),
            ),
            expected_targets=[],
        )
    assert "not formatted correctly; at" in str(exc.value)


def test_bad_req_type(rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError) as exc:
        assert_poetry_requirements(
            rule_runner,
            "poetry_requirements()",
            """
            [tool.poetry.dependencies]
            foo = 4
            [tool.poetry.dev-dependencies]
            """,
            expected_file_dep=PythonRequirementsFile(
                {"sources": ["pyproject.toml"]},
                address=Address("", target_name="pyproject.toml"),
            ),
            expected_targets=[],
        )
    assert "was of type int" in str(exc.value)


def test_no_tool_poetry(rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError) as exc:
        assert_poetry_requirements(
            rule_runner,
            "poetry_requirements()",
            """
            foo = 4
            """,
            expected_file_dep=PythonRequirementsFile(
                {"sources": ["pyproject.toml"]},
                address=Address("", target_name="pyproject.toml"),
            ),
            expected_targets=[],
        )
    assert "`tool.poetry` found in pyproject.toml" in str(exc.value)
