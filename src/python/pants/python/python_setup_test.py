# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager

from pants.python.python_setup import PythonSetup
from pants.testutil.pexrc_util import setup_pexrc_with_pex_python_path
from pants.testutil.test_base import TestBase
from pants.util.contextutil import environment_as, temporary_dir


@contextmanager
def fake_pyenv_root(fake_versions, fake_local_version):
    with temporary_dir() as pyenv_root:
        fake_version_dirs = [os.path.join(pyenv_root, "versions", v, "bin") for v in fake_versions]
        for d in fake_version_dirs:
            os.makedirs(d)
        fake_local_version_dirs = [os.path.join(pyenv_root, "versions", fake_local_version, "bin")]
        yield pyenv_root, fake_version_dirs, fake_local_version_dirs


class TestPythonSetup(TestBase):
    def test_get_environment_paths(self):
        with environment_as(PATH="foo/bar:baz:/qux/quux"):
            paths = PythonSetup.get_environment_paths()
        self.assertListEqual(["foo/bar", "baz", "/qux/quux"], paths)

    def test_get_pex_python_paths(self):
        with setup_pexrc_with_pex_python_path(["foo/bar", "baz", "/qux/quux"]):
            paths = PythonSetup.get_pex_python_paths()
        self.assertListEqual(["foo/bar", "baz", "/qux/quux"], paths)

    def test_get_pyenv_paths(self):
        local_pyenv_version = "3.5.5"
        all_pyenv_versions = ["2.7.14", local_pyenv_version]
        self.create_file(".python-version", local_pyenv_version + "\n")
        with fake_pyenv_root(all_pyenv_versions, local_pyenv_version) as (
            pyenv_root,
            expected_paths,
            expected_local_paths,
        ):
            paths = PythonSetup.get_pyenv_paths(pyenv_root_func=lambda: pyenv_root)
            local_paths = PythonSetup.get_pyenv_paths(
                pyenv_root_func=lambda: pyenv_root, pyenv_local=True
            )
        assert expected_paths == paths
        assert expected_local_paths == local_paths

    def test_expand_interpreter_search_paths(self):

        local_pyenv_version = "3.5.5"
        all_pyenv_versions = ["2.7.14", local_pyenv_version]
        self.create_file(".python-version", local_pyenv_version + "\n")
        with environment_as(PATH="/env/path1:/env/path2"):
            with setup_pexrc_with_pex_python_path(["/pexrc/path1:/pexrc/path2"]):
                with fake_pyenv_root(all_pyenv_versions, local_pyenv_version) as (
                    pyenv_root,
                    expected_pyenv_paths,
                    expected_pyenv_local_paths,
                ):
                    paths = [
                        "/foo",
                        "<PATH>",
                        "/bar",
                        "<PEXRC>",
                        "/baz",
                        "<PYENV>",
                        "<PYENV_LOCAL>",
                        "/qux",
                    ]
                    expanded_paths = PythonSetup.expand_interpreter_search_paths(
                        paths, pyenv_root_func=lambda: pyenv_root
                    )

        expected = (
            ["/foo", "/env/path1", "/env/path2", "/bar", "/pexrc/path1", "/pexrc/path2", "/baz"]
            + expected_pyenv_paths
            + expected_pyenv_local_paths
            + ["/qux"]
        )
        self.assertListEqual(expected, expanded_paths)
