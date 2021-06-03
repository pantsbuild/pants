from pkg_resources import Requirement

from pants.backend.python.macros.poetry_project import (
    get_max_caret,
    get_max_tilde,
    handle_dict_attr,
    handle_str_attr,
    parse_pyproject_toml,
    parse_single_dependency,
)

# TODO: pytest parameterize for caret/tilde edge


def test_max_caret_1() -> None:
    assert get_max_caret("", "1.2.3") == "2.0.0"


def test_max_caret_2() -> None:
    assert get_max_caret("", "1.2") == "2.0.0"


def test_max_caret_3() -> None:
    assert get_max_caret("", "1") == "2.0.0"


def test_max_caret_4() -> None:
    assert get_max_caret("", "0.2.3") == "0.3.0"


def test_max_caret_5() -> None:
    assert get_max_caret("", "0.0.3") == "0.0.4"


def test_max_caret_6() -> None:
    assert get_max_caret("", "0.0") == "0.1.0"


def test_max_caret_7() -> None:
    assert get_max_caret("", "0") == "1.0.0"


def test_max_tilde_1() -> None:
    assert get_max_tilde("", "1.2.3") == "1.3.0"


def test_max_tilde_2() -> None:
    assert get_max_tilde("", "1.2") == "1.3.0"


def test_max_tilde_3() -> None:
    assert get_max_tilde("", "1") == "2.0.0"


def test_max_tilde_4() -> None:
    assert get_max_tilde("", "0") == "1.0.0"


def test_handle_str_tilde() -> None:
    assert handle_str_attr("foo", "~1.2.3") == "foo >=1.2.3,<1.3.0"


def test_handle_str_caret() -> None:
    assert handle_str_attr("foo", "^1.2.3") == "foo >=1.2.3,<2.0.0"


def test_handle_compat_operator() -> None:
    assert handle_str_attr("foo", "~=1.2.3") == "foo ~=1.2.3"


def test_handle_no_operator() -> None:
    assert handle_str_attr("foo", "1.2.3") == "foo ==1.2.3"


def test_handle_one_char_operator() -> None:
    assert handle_str_attr("foo", ">1.2.3") == "foo >1.2.3"


def test_handle_multiple_reqs() -> None:
    assert handle_str_attr("foo", "~1.2, !=1.2.10") == "foo >=1.2,<1.3.0,!=1.2.10"


def test_handle_git_basic() -> None:
    attr = {"git": "https://github.com/requests/requests.git"}
    assert (
        handle_dict_attr("requests", attr)
        == "requests @ git+https://github.com/requests/requests.git"
    )


# TODO: conglomerate git/etc with kwargs (parameterize dict)
def test_handle_git_branch() -> None:
    attr = {"git": "https://github.com/requests/requests.git", "branch": "main"}
    assert (
        handle_dict_attr("requests", attr)
        == "requests @ git+https://github.com/requests/requests.git@main"
    )


def test_handle_git_tag() -> None:
    attr = {"git": "https://github.com/requests/requests.git", "tag": "v1.1.1"}
    assert (
        handle_dict_attr("requests", attr)
        == "requests @ git+https://github.com/requests/requests.git@v1.1.1"
    )


def test_handle_git_revision() -> None:
    attr = {"git": "https://github.com/requests/requests.git", "rev": "1a2b3c4d"}
    assert (
        handle_dict_attr("requests", attr)
        == "requests @ git+https://github.com/requests/requests.git#1a2b3c4d"
    )


def test_handle_path_arg() -> None:
    attr = {"path": "../../my_py_proj.whl"}
    assert handle_dict_attr("my_py_proj", attr) == "my_py_proj @ file://../../my_py_proj.whl"


def test_handle_url_arg() -> None:
    attr = {"url": "https://my-site.com/mydep.whl"}
    assert handle_dict_attr("my_py_proj", attr) == "my_py_proj @ https://my-site.com/mydep.whl"


def test_version_only() -> None:
    attr = {"version": "1.2.3"}
    assert handle_dict_attr("foo", attr) == "foo ==1.2.3"


def test_py_constraint_single() -> None:
    attr = {"version": "1.2.3", "python": "3.6"}
    assert handle_dict_attr("foo", attr) == "foo ==1.2.3;python_version == '3.6'"


def test_py_constraint_or() -> None:
    attr = {"version": "1.2.3", "python": "3.6 || 3.7"}
    assert (
        handle_dict_attr("foo", attr)
        == "foo ==1.2.3;(python_version == '3.6') or (python_version == '3.7')"
    )


def test_py_constraint_and() -> None:
    attr = {"version": "1.2.3", "python": ">3.6,!=3.7"}
    assert (
        handle_dict_attr("foo", attr)
        == "foo ==1.2.3;python_version > '3.6' and python_version != '3.7'"
    )


def test_py_constraint_and_or() -> None:
    attr = {"version": "1.2.3", "python": ">3.6 || 3.5,3.4"}
    assert (
        handle_dict_attr("foo", attr)
        == "foo ==1.2.3;(python_version > '3.6') or (python_version == '3.5' and python_version == '3.4')"
    )


def test_py_constraint_tilde_caret_and_or() -> None:
    attr = {"version": "1.2.3", "python": "~3.6 || ^3.7"}
    assert (
        handle_dict_attr("foo", attr)
        == "foo ==1.2.3;(python_version >= '3.6' and python_version< '3.7') or (python_version >= '3.7' and python_version< '4.0')"
    )


def test_multi_version_const() -> None:
    lst_attr = [{"version": "1.2.3", "python": "3.6"}, {"version": "1.2.4", "python": "3.7"}]
    retval = parse_single_dependency("foo", lst_attr)
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
    retval = parse_pyproject_toml(toml_black_str)
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
    retval = parse_pyproject_toml(toml_str)
    actual_reqs = {
        Requirement.parse("python<4.0.0,>=3.8"),
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
