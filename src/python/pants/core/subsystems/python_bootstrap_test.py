# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterable, List, Sequence, TypeVar

import pytest

from pants.base.build_environment import get_pants_cachedir
from pants.core.subsystems.python_bootstrap import (
    _ExpandInterpreterSearchPathsRequest,
    _get_environment_paths,
    _get_pex_python_paths,
    _get_pyenv_root,
    _preprocessed_interpreter_search_paths,
    _PyEnvPathsRequest,
    _SearchPaths,
)
from pants.core.subsystems.python_bootstrap import rules as python_bootstrap_rules
from pants.core.util_rules import asdf
from pants.core.util_rules.asdf import AsdfToolPathsRequest, AsdfToolPathsResult
from pants.core.util_rules.asdf_test import fake_asdf_root
from pants.core.util_rules.environments import (
    DockerEnvironmentTarget,
    DockerImageField,
    EnvironmentTarget,
    LocalEnvironmentTarget,
    RemoteEnvironmentTarget,
)
from pants.engine.addresses import Address
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import environment_as, temporary_dir
from pants.util.dirutil import safe_mkdir_for

_T = TypeVar("_T")


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *python_bootstrap_rules(),
            *asdf.rules(),
            QueryRule(AsdfToolPathsResult, (AsdfToolPathsRequest,)),
            QueryRule(_SearchPaths, [_PyEnvPathsRequest]),
            QueryRule(_SearchPaths, [_ExpandInterpreterSearchPathsRequest]),
        ],
        target_types=[],
    )


@contextmanager
def setup_pexrc_with_pex_python_path(interpreter_paths):
    """A helper function for writing interpreter paths to a PEX_PYTHON_PATH variable in a .pexrc
    file.

    NB: Mutates HOME and XDG_CACHE_HOME to ensure a `~/.pexrc` that won't trample any existing file
    and will also be found.

    :param list interpreter_paths: a list of paths to interpreter binaries to include on
                                   PEX_PYTHON_PATH.
    """
    cache_dir = get_pants_cachedir()
    with temporary_dir() as home:
        xdg_cache_home = os.path.join(home, ".cache")
        with environment_as(HOME=home, XDG_CACHE_HOME=xdg_cache_home):
            target = os.path.join(xdg_cache_home, os.path.basename(cache_dir))
            safe_mkdir_for(target)
            os.symlink(cache_dir, target)

            with open(os.path.join(home, ".pexrc"), "w") as pexrc:
                pexrc.write(f"PEX_PYTHON_PATH={':'.join(interpreter_paths)}")

            yield


@contextmanager
def fake_pyenv_root(fake_versions, fake_local_version):
    with temporary_dir() as pyenv_root:
        fake_version_dirs = tuple(
            os.path.join(pyenv_root, "versions", v, "bin") for v in fake_versions
        )
        for d in fake_version_dirs:
            os.makedirs(d)
        fake_local_version_dirs = (os.path.join(pyenv_root, "versions", fake_local_version, "bin"),)
        yield pyenv_root, fake_version_dirs, fake_local_version_dirs


def materialize_indices(sequence: Sequence[_T], indices: Iterable[int]) -> List[_T]:
    return [sequence[i] for i in indices]


def test_get_environment_paths() -> None:
    paths = _get_environment_paths(EnvironmentVars({"PATH": "foo/bar:baz:/qux/quux"}))
    assert ["foo/bar", "baz", "/qux/quux"] == paths


def test_get_pex_python_paths() -> None:
    with setup_pexrc_with_pex_python_path(["foo/bar", "baz", "/qux/quux"]):
        paths = _get_pex_python_paths()
    assert ["foo/bar", "baz", "/qux/quux"] == paths


def test_get_pyenv_root() -> None:
    home = "/♡"
    default_root = f"{home}/.pyenv"
    explicit_root = f"{home}/explicit"

    assert explicit_root == _get_pyenv_root(EnvironmentVars({"PYENV_ROOT": explicit_root}))
    assert default_root == _get_pyenv_root(EnvironmentVars({"HOME": home}))
    assert _get_pyenv_root(EnvironmentVars({})) is None


def test_get_pyenv_paths(rule_runner: RuleRunner) -> None:
    local_pyenv_version = "3.5.5"
    all_pyenv_versions = ["2.7.14", local_pyenv_version]
    rule_runner.write_files({".python-version": f"{local_pyenv_version}\n"})
    with fake_pyenv_root(all_pyenv_versions, local_pyenv_version) as (
        pyenv_root,
        expected_paths,
        expected_local_paths,
    ):
        rule_runner.set_session_values(
            {CompleteEnvironmentVars: CompleteEnvironmentVars({"PYENV_ROOT": pyenv_root})}
        )
        tgt = EnvironmentTarget(LocalEnvironmentTarget({}, Address("flem")))
        paths = rule_runner.request(
            _SearchPaths,
            [_PyEnvPathsRequest(tgt, False)],
        )
        local_paths = rule_runner.request(
            _SearchPaths,
            [_PyEnvPathsRequest(tgt, True)],
        )
    assert expected_paths == paths.paths
    assert expected_local_paths == local_paths.paths


def test_expand_interpreter_search_paths(rule_runner: RuleRunner) -> None:
    local_pyenv_version = "3.5.5"
    all_python_versions = ["2.7.14", local_pyenv_version, "3.7.10", "3.9.4", "3.9.5"]
    asdf_home_versions = [0, 1, 2]
    asdf_local_versions = [2, 1, 4]
    asdf_local_versions_str = " ".join(
        materialize_indices(all_python_versions, asdf_local_versions)
    )
    rule_runner.write_files(
        {
            ".python-version": f"{local_pyenv_version}\n",
            ".tool-versions": "\n".join(
                [
                    "nodejs 16.0.1",
                    "java current",
                    f"python {asdf_local_versions_str}",
                    "rust 1.52.0",
                ]
            ),
        }
    )
    with setup_pexrc_with_pex_python_path(["/pexrc/path1:/pexrc/path2"]):
        with fake_asdf_root(
            all_python_versions, asdf_home_versions, asdf_local_versions, tool_name="python"
        ) as (
            home_dir,
            asdf_dir,
            expected_asdf_paths,
            expected_asdf_home_paths,
            expected_asdf_local_paths,
        ), fake_pyenv_root(
            all_python_versions, local_pyenv_version
        ) as (
            pyenv_root,
            expected_pyenv_paths,
            expected_pyenv_local_paths,
        ):
            rule_runner.set_session_values(
                {
                    CompleteEnvironmentVars: CompleteEnvironmentVars(
                        {
                            "HOME": home_dir,
                            "PATH": "/env/path1:/env/path2",
                            "PYENV_ROOT": pyenv_root,
                            "ASDF_DATA_DIR": asdf_dir,
                        },
                    )
                }
            )

            paths = (
                "/foo",
                "<PATH>",
                "/bar",
                "<PEXRC>",
                "/baz",
                "<ASDF>",
                "<ASDF_LOCAL>",
                "<PYENV>",
                "<PYENV_LOCAL>",
                "/qux",
            )
            expanded_paths = rule_runner.request(
                _SearchPaths,
                [
                    _ExpandInterpreterSearchPathsRequest(
                        paths,
                        EnvironmentTarget(LocalEnvironmentTarget({}, Address("flem"))),
                    )
                ],
            )

    expected = (
        "/foo",
        "/env/path1",
        "/env/path2",
        "/bar",
        "/pexrc/path1",
        "/pexrc/path2",
        "/baz",
        *expected_asdf_home_paths,
        *expected_asdf_local_paths,
        *expected_pyenv_paths,
        *expected_pyenv_local_paths,
        "/qux",
    )
    assert expected == expanded_paths.paths


@pytest.mark.parametrize(
    ("env_tgt_type", "search_paths", "is_default", "expected"),
    (
        (LocalEnvironmentTarget, ("<PYENV>",), False, ("<PYENV>",)),
        (LocalEnvironmentTarget, ("<ASDF>",), False, ("<ASDF>",)),
        (
            LocalEnvironmentTarget,
            ("<ASDF_LOCAL>", "/home/derryn/pythons"),
            False,
            ("<ASDF_LOCAL>", "/home/derryn/pythons"),
        ),
        (DockerEnvironmentTarget, ("<PYENV>", "<PATH>"), True, ("<PATH>",)),
        (DockerEnvironmentTarget, ("<PYENV>", "<PATH>"), False, ValueError),
        (DockerEnvironmentTarget, ("<PYENV>", "<PATH>"), False, ValueError),
        (
            DockerEnvironmentTarget,
            ("<ASDF>", "/home/derryn/pythons"),
            False,
            ValueError,
        ),  # Contains a banned special-string
        (DockerEnvironmentTarget, ("<ASDF_LOCAL>",), False, ValueError),
        (DockerEnvironmentTarget, ("<PYENV_LOCAL>",), False, ValueError),
        (DockerEnvironmentTarget, ("<PEXRC>",), False, ValueError),
        (DockerEnvironmentTarget, ("<PATH>",), False, ("<PATH>",)),
        (
            DockerEnvironmentTarget,
            ("<PATH>", "/home/derryn/pythons"),
            False,
            ("<PATH>", "/home/derryn/pythons"),
        ),
        (RemoteEnvironmentTarget, ("<PYENV>", "<PATH>"), True, ("<PATH>",)),
        (RemoteEnvironmentTarget, ("<PYENV>", "<PATH>"), False, ValueError),
        (RemoteEnvironmentTarget, ("<PYENV>", "<PATH>"), False, ValueError),
        (
            RemoteEnvironmentTarget,
            ("<ASDF>", "/home/derryn/pythons"),
            False,
            ValueError,
        ),  # Contains a banned special-string
        (RemoteEnvironmentTarget, ("<ASDF_LOCAL>",), False, ValueError),
        (RemoteEnvironmentTarget, ("<PYENV_LOCAL>",), False, ValueError),
        (RemoteEnvironmentTarget, ("<PEXRC>",), False, ValueError),
        (RemoteEnvironmentTarget, ("<PATH>",), False, ("<PATH>",)),
        (
            RemoteEnvironmentTarget,
            ("<PATH>", "/home/derryn/pythons"),
            False,
            ("<PATH>", "/home/derryn/pythons"),
        ),
    ),
)
def test_preprocessed_interpreter_search_paths(
    env_tgt_type: type[LocalEnvironmentTarget]
    | type[DockerEnvironmentTarget]
    | type[RemoteEnvironmentTarget],
    search_paths: Iterable[str],
    is_default: bool,
    expected: tuple[str] | type[ValueError],
):
    extra_kwargs: dict = {}
    if env_tgt_type is DockerEnvironmentTarget:
        extra_kwargs = {
            DockerImageField.alias: "my_img",
        }

    env_tgt = EnvironmentTarget(env_tgt_type(extra_kwargs, address=Address("flem")))
    if expected is not ValueError:
        assert expected == _preprocessed_interpreter_search_paths(env_tgt, search_paths, is_default)
    else:
        with pytest.raises(ValueError):
            _preprocessed_interpreter_search_paths(env_tgt, search_paths, is_default)
