# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path, PurePath
from textwrap import dedent

import pytest
from packaging.version import Version

from pants.backend.python.goals import lockfile
from pants.backend.python.macros import poetry_requirements
from pants.backend.python.macros.poetry_requirements import (
    PoetryRequirementsTargetGenerator,
    PyprojectAttr,
    PyProjectToml,
    add_markers,
    get_max_caret,
    get_max_tilde,
    handle_dict_attr,
    parse_pyproject_toml,
    parse_single_dependency,
    parse_str_version,
)
from pants.backend.python.target_types import PythonRequirementTarget
from pants.core.target_types import TargetGeneratorSourcesHelperTarget
from pants.engine.addresses import Address
from pants.engine.internals.graph import _TargetParametrizations, _TargetParametrizationsRequest
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error
from pants.util.pip_requirement import PipRequirement
from pants.util.strutil import softwrap

# ---------------------------------------------------------------------------------
# pyproject.toml parsing
# ---------------------------------------------------------------------------------


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
        ("*", ""),
        ("1.*", ">=1.0,<2.0.0"),
        ("1.2.*", ">=1.2.0,<1.3.0"),
    ],
)
def test_wildcard(test, exp) -> None:
    assert (
        parse_str_version(test, proj_name="foo", file_path="", extras_str="")
        == f"foo {exp}".rstrip()
    )


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
    assert parse_str_version(test, proj_name="foo", file_path="", extras_str="") == f"foo {exp}"


def assert_equal_requirements(actual: str | None, expected: str) -> None:
    assert actual is not None
    assert PipRequirement.parse(expected) == PipRequirement.parse(actual)


def test_add_markers() -> None:
    attr_mark = PyprojectAttr(markers="platform_python_implementation == 'CPython'")
    assert_equal_requirements(
        add_markers("foo==1.0.0", attr_mark, "somepath"),
        "foo==1.0.0;(platform_python_implementation == 'CPython')",
    )

    attr_mark_adv = PyprojectAttr(
        markers="platform_python_implementation == 'CPython' or sys_platform == 'win32'"
    )
    assert_equal_requirements(
        add_markers("foo==1.0.0", attr_mark_adv, "somepath"),
        "foo==1.0.0;(platform_python_implementation == 'CPython' or sys_platform == 'win32')",
    )
    attr_basic_both = PyprojectAttr(python="3.6")
    attr_basic_both.update(attr_mark)

    assert_equal_requirements(
        add_markers("foo==1.0.0", attr_basic_both, "somepath"),
        "foo==1.0.0;(platform_python_implementation == 'CPython') and (python_version == '3.6')",
    )
    attr_adv_py_both = PyprojectAttr(
        python="^3.6", markers="platform_python_implementation == 'CPython'"
    )
    assert_equal_requirements(
        add_markers("foo==1.0.0", attr_adv_py_both, "somepath"),
        softwrap(
            """
            foo==1.0.0;(platform_python_implementation == 'CPython') and
            (python_version >= '3.6' and python_version< '4.0')
            """
        ),
    )

    attr_adv_both = PyprojectAttr(
        python="^3.6",
        markers="platform_python_implementation == 'CPython' or sys_platform == 'win32'",
    )
    assert_equal_requirements(
        add_markers("foo==1.0.0", attr_adv_both, "somepath"),
        softwrap(
            """
            foo==1.0.0;(platform_python_implementation == 'CPython' or
            sys_platform == 'win32') and (python_version >= '3.6' and python_version< '4.0')
            """
        ),
    )


def create_pyproject_toml(
    build_root: PurePath | str = ".",
    toml_relpath: PurePath | str = "pyproject.toml",
    toml_contents: str = "",
) -> PyProjectToml:
    return PyProjectToml(
        build_root=PurePath(build_root),
        toml_relpath=PurePath(toml_relpath),
        toml_contents=toml_contents,
    )


@pytest.fixture
def empty_pyproject_toml() -> PyProjectToml:
    return create_pyproject_toml(toml_contents="")


def test_handle_extras(empty_pyproject_toml: PyProjectToml) -> None:
    # The case where we have both extras and path/url are tested in
    # test_handle_path/url respectively.
    attr = PyprojectAttr(version="1.0.0", extras=["extra1"])
    assert handle_dict_attr("requests", attr, empty_pyproject_toml) == "requests[extra1] ==1.0.0"

    attr_git = PyprojectAttr(git="https://github.com/requests/requests.git", extras=["extra1"])
    assert (
        handle_dict_attr("requests", attr_git, empty_pyproject_toml)
        == "requests[extra1] @ git+https://github.com/requests/requests.git"
    )

    assert handle_dict_attr("requests", attr, empty_pyproject_toml) == "requests[extra1] ==1.0.0"
    attr_multi = PyprojectAttr(version="1.0.0", extras=["extra1", "extra2", "extra3"])
    assert (
        handle_dict_attr("requests", attr_multi, empty_pyproject_toml)
        == "requests[extra1,extra2,extra3] ==1.0.0"
    )


def test_handle_git(empty_pyproject_toml: PyProjectToml) -> None:
    def assert_git(extra_opts: PyprojectAttr, suffix: str) -> None:
        attr = PyprojectAttr(git="https://github.com/requests/requests.git")
        attr.update(extra_opts)
        assert_equal_requirements(
            handle_dict_attr("requests", attr, empty_pyproject_toml),
            f"requests @ git+https://github.com/requests/requests.git{suffix}",
        )

    assert_git({}, "")
    assert_git(PyprojectAttr(branch="main"), "@main")
    assert_git(PyprojectAttr(tag="v1.1.1"), "@v1.1.1")
    assert_git(PyprojectAttr(rev="1a2b3c4d"), "#1a2b3c4d")
    assert_git(
        PyprojectAttr(
            branch="main",
            markers="platform_python_implementation == 'CPython'",
            python="3.6",
        ),
        "@main ;(platform_python_implementation == 'CPython') and (python_version == '3.6')",
    )


def test_handle_git_ssh(empty_pyproject_toml: PyProjectToml) -> None:
    attr = PyprojectAttr(git="git@github.com:requests/requests.git")
    assert (
        handle_dict_attr("requests", attr, empty_pyproject_toml)
        == "requests @ git+ssh://git@github.com/requests/requests.git"
    )


def test_handle_path_arg(tmp_path: Path) -> None:
    build_root = tmp_path / "build_root"

    one_level = Path("one")
    one_pyproject_toml = create_pyproject_toml(
        build_root=build_root, toml_relpath=one_level / "pyproject.toml"
    )

    two_level = one_level / "two"
    two_pyproject_toml = create_pyproject_toml(
        build_root=build_root, toml_relpath=two_level / "pyproject.toml"
    )

    (build_root / two_level).mkdir(parents=True)

    external_file = tmp_path / "my_py_proj.whl"
    external_file.touch()

    external_project = tmp_path / "my_py_proj"
    external_project.mkdir()

    internal_file = build_root / "my_py_proj.whl"
    internal_file.touch()

    internal_project = build_root / "my_py_proj"
    internal_project.mkdir()

    file_attr = PyprojectAttr(path="../../my_py_proj.whl")
    file_attr_mark = PyprojectAttr(path="../../my_py_proj.whl", markers="os_name=='darwin'")
    file_attr_extras = PyprojectAttr(path="../../my_py_proj.whl", extras=["extra1"])
    dir_attr = PyprojectAttr(path="../../my_py_proj")

    assert_equal_requirements(
        handle_dict_attr("my_py_proj", file_attr, one_pyproject_toml),
        f"my_py_proj @ file://{external_file}",
    )

    assert_equal_requirements(
        handle_dict_attr("my_py_proj", file_attr_extras, one_pyproject_toml),
        f"my_py_proj[extra1] @ file://{external_file}",
    )

    assert_equal_requirements(
        handle_dict_attr("my_py_proj", file_attr_mark, one_pyproject_toml),
        f"my_py_proj @ file://{external_file} ;(os_name=='darwin')",
    )

    assert_equal_requirements(
        handle_dict_attr("my_py_proj", file_attr, two_pyproject_toml),
        f"my_py_proj @ file://{internal_file}",
    )

    assert_equal_requirements(
        handle_dict_attr("my_py_proj", dir_attr, one_pyproject_toml),
        f"my_py_proj @ file://{external_project}",
    )

    assert handle_dict_attr("my_py_proj", dir_attr, two_pyproject_toml) is None


def test_handle_url_arg(empty_pyproject_toml: PyProjectToml) -> None:
    attr = PyprojectAttr(url="https://my-site.com/mydep.whl")
    assert_equal_requirements(
        handle_dict_attr("my_py_proj", attr, empty_pyproject_toml),
        "my_py_proj @ https://my-site.com/mydep.whl",
    )

    attr_with_extra = PyprojectAttr(extras=["extra1"])
    attr_with_extra.update(attr)
    assert_equal_requirements(
        handle_dict_attr("my_py_proj", attr_with_extra, empty_pyproject_toml),
        "my_py_proj[extra1] @ https://my-site.com/mydep.whl",
    )

    attr_with_mark = PyprojectAttr(markers="os_name=='darwin'")
    attr_with_mark.update(attr)
    assert_equal_requirements(
        handle_dict_attr("my_py_proj", attr_with_mark, empty_pyproject_toml),
        "my_py_proj @ https://my-site.com/mydep.whl ;(os_name=='darwin')",
    )


def test_version_only(empty_pyproject_toml: PyProjectToml) -> None:
    attr = PyprojectAttr(version="1.2.3")
    assert handle_dict_attr("foo", attr, empty_pyproject_toml) == "foo ==1.2.3"


def test_py_constraints(empty_pyproject_toml: PyProjectToml) -> None:
    def assert_py_constraints(py_req: str, suffix: str) -> None:
        attr = PyprojectAttr(version="1.2.3", python=py_req)
        assert_equal_requirements(
            handle_dict_attr("foo", attr, empty_pyproject_toml), f"foo ==1.2.3;{suffix}"
        )

    assert_py_constraints("3.6", "(python_version == '3.6')")
    assert_py_constraints("3.6 || 3.7", "((python_version == '3.6') or (python_version == '3.7'))")
    assert_py_constraints(">3.6,!=3.7", "(python_version > '3.6' and python_version != '3.7')")
    assert_py_constraints(
        ">3.6 || 3.5,3.4",
        "((python_version > '3.6') or (python_version == '3.5' and python_version == '3.4'))",
    )
    assert_py_constraints(
        "~3.6 || ^3.7",
        softwrap(
            """
            ((python_version >= '3.6' and python_version< '3.7') or
            (python_version >= '3.7' and python_version< '4.0'))
            """
        ),
    )


def test_multi_version_const(empty_pyproject_toml: PyProjectToml) -> None:
    lst_attr = [{"version": "1.2.3", "python": "3.6"}, {"version": "1.2.4", "python": "3.7"}]
    retval = tuple(parse_single_dependency("foo", lst_attr, empty_pyproject_toml))
    actual_reqs = (
        PipRequirement.parse("foo ==1.2.3; python_version == '3.6'"),
        PipRequirement.parse("foo ==1.2.4; python_version == '3.7'"),
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
    pyproject_toml_black = create_pyproject_toml(toml_contents=toml_black_str)
    retval = parse_pyproject_toml(pyproject_toml_black)
    actual_req = {
        PipRequirement.parse(
            softwrap(
                """
                black==19.10b0;
                platform_python_implementation == "CPython" and python_version == "3.6"
                """
            )
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
    junk = {url = "https://github.com/myrepo/junk.whl", extras = ["security"]}
    poetry = {git = "https://github.com/python-poetry/poetry.git", tag = "v1.1.1"}
    requests = {extras = ["security","random"], version = "^2.25.1", python = ">2.7"}
    foo = [{version = ">=1.9", python = "^2.7"},{version = "^2.0", python = "3.4 || 3.5"}]

    [tool.poetry.dependencies.black]
    version = "19.10b0"
    python = "3.6"
    markers = "platform_python_implementation == 'CPython'"

    [tool.poetry.group.mygroup.dependencies]
    myrequirement = "1.2.3"
    awildcard = "6.7.*"
    anotherwildcard = "44.*"
    aglobalwildcard = "*"

    [tool.poetry.group.mygroup2.dependencies]
    myrequirement2 = "1.2.3"

    [tool.poetry.dev-dependencies]
    isort = ">=5.5.1,<5.6"

    [build-system]
    requires = ["poetry-core>=1.0.0"]
    build-backend = "poetry.core.masonry.api"
    """
    pyproject_toml = create_pyproject_toml(toml_contents=toml_str)
    retval = parse_pyproject_toml(pyproject_toml)
    actual_reqs = {
        PipRequirement.parse("junk[security]@ https://github.com/myrepo/junk.whl"),
        PipRequirement.parse("myrequirement==1.2.3"),
        PipRequirement.parse("awildcard>=6.7.0,<6.8.0"),
        PipRequirement.parse("anotherwildcard>=44.0,<45.0.0"),
        PipRequirement.parse("aglobalwildcard"),
        PipRequirement.parse("myrequirement2==1.2.3"),
        PipRequirement.parse("poetry@ git+https://github.com/python-poetry/poetry.git@v1.1.1"),
        PipRequirement.parse('requests[security, random]<3.0.0,>=2.25.1; python_version > "2.7"'),
        PipRequirement.parse('foo>=1.9; python_version >= "2.7" and python_version < "3.0"'),
        PipRequirement.parse('foo<3.0.0,>=2.0; python_version == "3.4" or python_version == "3.5"'),
        PipRequirement.parse(
            softwrap(
                """
                black==19.10b0;
                platform_python_implementation == "CPython" and python_version == "3.6"
                """
            ).strip()
        ),
        PipRequirement.parse("isort<5.6,>=5.5.1"),
    }
    assert retval == actual_reqs


# ---------------------------------------------------------------------------------
# Target generator
# ---------------------------------------------------------------------------------


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *lockfile.rules(),
            *poetry_requirements.rules(),
            QueryRule(_TargetParametrizations, [_TargetParametrizationsRequest]),
        ],
        target_types=[PoetryRequirementsTargetGenerator],
    )


def assert_poetry_requirements(
    rule_runner: RuleRunner,
    build_file_entry: str,
    pyproject_toml: str,
    *,
    expected_targets: set[Target],
    pyproject_toml_relpath: str = "pyproject.toml",
) -> None:
    rule_runner.write_files({"BUILD": build_file_entry, pyproject_toml_relpath: pyproject_toml})
    result = rule_runner.request(
        _TargetParametrizations,
        [
            _TargetParametrizationsRequest(
                Address("", target_name="reqs"), description_of_origin="tests"
            )
        ],
    )
    assert set(result.parametrizations.values()) == expected_targets


def test_pyproject_toml(rule_runner: RuleRunner) -> None:
    """This tests that we correctly create a new python_requirement for each entry in a
    pyproject.toml file.

    Note that this just ensures proper targets are created; see prior tests for specific parsing
    edge cases.
    """
    file_addr = Address("", target_name="reqs", relative_file_path="pyproject.toml")
    assert_poetry_requirements(
        rule_runner,
        dedent(
            """\
            poetry_requirements(
                name="reqs",
                # module_mapping should work regardless of capitalization.
                module_mapping={'ansiCOLORS': ['colors']},
                type_stubs_module_mapping={'Django-types': ['django']},
                overrides={"Django": {"dependencies": ["#Django-types"]}},
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
        expected_targets={
            PythonRequirementTarget(
                {
                    "dependencies": [file_addr.spec],
                    "requirements": ["ansicolors>=1.18.0"],
                    "modules": ["colors"],
                },
                address=Address("", target_name="reqs", generated_name="ansicolors"),
            ),
            PythonRequirementTarget(
                {
                    "dependencies": ["#Django-types", file_addr.spec],
                    "requirements": ["Django==3.2 ; python_version == '3'"],
                },
                address=Address("", target_name="reqs", generated_name="Django"),
            ),
            PythonRequirementTarget(
                {
                    "dependencies": [file_addr.spec],
                    "requirements": ["Django-types==2"],
                    "type_stub_modules": ["django"],
                },
                address=Address("", target_name="reqs", generated_name="Django-types"),
            ),
            PythonRequirementTarget(
                {
                    "dependencies": [file_addr.spec],
                    "requirements": ["Un_Normalized_PROJECT == 1.0.0"],
                },
                address=Address("", target_name="reqs", generated_name="Un-Normalized-PROJECT"),
            ),
            TargetGeneratorSourcesHelperTarget({"source": "pyproject.toml"}, file_addr),
        },
    )


def test_source_override(rule_runner: RuleRunner) -> None:
    file_addr = Address("", target_name="reqs", relative_file_path="subdir/pyproject.toml")
    assert_poetry_requirements(
        rule_runner,
        "poetry_requirements(name='reqs', source='subdir/pyproject.toml')",
        dedent(
            """\
            [tool.poetry.dependencies]
            ansicolors = ">=1.18.0"
            [tool.poetry.dev-dependencies]
            """
        ),
        pyproject_toml_relpath="subdir/pyproject.toml",
        expected_targets={
            PythonRequirementTarget(
                {"dependencies": [file_addr.spec], "requirements": ["ansicolors>=1.18.0"]},
                address=Address("", target_name="reqs", generated_name="ansicolors"),
            ),
            TargetGeneratorSourcesHelperTarget({"source": "subdir/pyproject.toml"}, file_addr),
        },
    )


def test_lockfile_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--python-enable-resolves"])
    file_addr = Address("", target_name="reqs", relative_file_path="pyproject.toml")
    lock_addr = Address(
        "3rdparty/python", target_name="_python-default_lockfile", relative_file_path="default.lock"
    )
    assert_poetry_requirements(
        rule_runner,
        "poetry_requirements(name='reqs')",
        dedent(
            """\
            [tool.poetry.dependencies]
            ansicolors = ">=1.18.0"
            [tool.poetry.dev-dependencies]
            """
        ),
        expected_targets={
            PythonRequirementTarget(
                {
                    "dependencies": [file_addr.spec, lock_addr.spec],
                    "requirements": ["ansicolors>=1.18.0"],
                },
                address=Address("", target_name="reqs", generated_name="ansicolors"),
            ),
            TargetGeneratorSourcesHelperTarget({"source": file_addr.filename}, file_addr),
        },
    )


def test_non_pep440_error(rule_runner: RuleRunner) -> None:
    with engine_error(contains='Failed to parse requirement foo = "~r62b" in pyproject.toml'):
        assert_poetry_requirements(
            rule_runner,
            "poetry_requirements(name='reqs')",
            """
            [tool.poetry.dependencies]
            foo = "~r62b"
            [tool.poetry.dev-dependencies]
            """,
            expected_targets=set(),
        )


def test_no_req_defined_warning(rule_runner: RuleRunner, caplog) -> None:
    assert_poetry_requirements(
        rule_runner,
        "poetry_requirements(name='reqs')",
        """
        [tool.poetry.dependencies]
        [tool.poetry.dev-dependencies]
        """,
        expected_targets={
            TargetGeneratorSourcesHelperTarget(
                {"source": "pyproject.toml"},
                Address("", target_name="reqs", relative_file_path="pyproject.toml"),
            )
        },
    )
    assert "No requirements defined" in caplog.text


def test_bad_dict_format(rule_runner: RuleRunner) -> None:
    with engine_error(contains="not formatted correctly; at"):
        assert_poetry_requirements(
            rule_runner,
            "poetry_requirements(name='reqs')",
            """
            [tool.poetry.dependencies]
            foo = {bad_req = "test"}
            [tool.poetry.dev-dependencies]
            """,
            expected_targets=set(),
        )


def test_bad_req_type(rule_runner: RuleRunner) -> None:
    with engine_error(contains="was of type int"):
        assert_poetry_requirements(
            rule_runner,
            "poetry_requirements(name='reqs')",
            """
            [tool.poetry.dependencies]
            foo = 4
            [tool.poetry.dev-dependencies]
            """,
            expected_targets=set(),
        )


def test_no_tool_poetry(rule_runner: RuleRunner) -> None:
    with engine_error(contains="`tool.poetry` found in pyproject.toml"):
        assert_poetry_requirements(
            rule_runner, "poetry_requirements(name='reqs')", "foo = 4", expected_targets=set()
        )
