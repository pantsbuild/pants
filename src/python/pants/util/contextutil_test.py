# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
import subprocess
import sys
import zipfile
from contextlib import contextmanager
from typing import Iterator

import pytest

from pants.util.contextutil import (
    InvalidZipPath,
    environment_as,
    hermetic_environment_as,
    open_zip,
    pushd,
    temporary_dir,
    temporary_file,
)


class TestContextutilTest:
    @contextmanager
    def ensure_user_defined_in_environment(self) -> Iterator[None]:
        """Utility to test for hermetic environments."""
        original_env = os.environ.copy()
        if "USER" not in original_env:
            os.environ["USER"] = "pantsbuild"
        try:
            yield
        finally:
            os.environ.clear()
            os.environ.update(original_env)

    def test_empty_environment(self) -> None:
        with environment_as():
            pass

    def test_override_single_variable(self) -> None:
        with temporary_file(binary_mode=False) as output:
            # test that the override takes place
            with environment_as(HORK="BORK"):
                subprocess.Popen(
                    [sys.executable, "-c", 'import os; print(os.environ["HORK"])'], stdout=output
                ).wait()
                output.seek(0)
                assert "BORK\n" == output.read()

            # test that the variable is cleared
            with temporary_file(binary_mode=False) as new_output:
                subprocess.Popen(
                    [sys.executable, "-c", 'import os; print("HORK" in os.environ)'],
                    stdout=new_output,
                ).wait()
                new_output.seek(0)
                assert "False\n" == new_output.read()

    def test_environment_negation(self) -> None:
        with temporary_file(binary_mode=False) as output:
            with environment_as(HORK="BORK"):
                with environment_as(HORK=None):
                    # test that the variable is cleared
                    subprocess.Popen(
                        [sys.executable, "-c", 'import os; print("HORK" in os.environ)'],
                        stdout=output,
                    ).wait()
                    output.seek(0)
                    assert "False\n" == output.read()

    def test_hermetic_environment(self) -> None:
        with self.ensure_user_defined_in_environment():
            with hermetic_environment_as():
                assert "USER" not in os.environ
        with self.ensure_user_defined_in_environment():
            with hermetic_environment_as("USER"):
                assert "USER" in os.environ

    def test_hermetic_environment_subprocesses(self) -> None:
        with self.ensure_user_defined_in_environment():
            with hermetic_environment_as(AAA="333"):
                output = subprocess.check_output("env", shell=True).decode()
                assert "USER=" not in output
                assert "AAA" in os.environ
                assert os.environ["AAA"] == "333"
            assert "USER" in os.environ
            assert "AAA" not in os.environ

    def test_hermetic_environment_unicode(self) -> None:
        with environment_as(XXX="¡"):
            assert os.environ["XXX"] == "¡"
            with hermetic_environment_as(AAA="¡"):
                assert "AAA" in os.environ
                assert os.environ["AAA"] == "¡"
            assert os.environ["XXX"] == "¡"

    def test_simple_pushd(self) -> None:
        pre_cwd = os.getcwd()
        with temporary_dir() as tempdir:
            with pushd(tempdir) as path:
                assert tempdir == path
                assert os.path.realpath(tempdir) == os.getcwd()
            assert pre_cwd == os.getcwd()
        assert pre_cwd == os.getcwd()

    def test_nested_pushd(self) -> None:
        pre_cwd = os.getcwd()
        with temporary_dir() as tempdir1:
            with pushd(tempdir1):
                assert os.path.realpath(tempdir1) == os.getcwd()
                with temporary_dir(root_dir=tempdir1) as tempdir2:
                    with pushd(tempdir2):
                        assert os.path.realpath(tempdir2) == os.getcwd()
                    assert os.path.realpath(tempdir1) == os.getcwd()
                assert os.path.realpath(tempdir1) == os.getcwd()
            assert pre_cwd == os.getcwd()
        assert pre_cwd == os.getcwd()

    def test_temporary_file_no_args(self) -> None:
        with temporary_file() as fp:
            assert os.path.exists(fp.name), "Temporary file should exist within the context."
        assert (
            os.path.exists(fp.name) is False
        ), "Temporary file should not exist outside of the context."

    def test_temporary_file_without_cleanup(self) -> None:
        with temporary_file(cleanup=False) as fp:
            assert os.path.exists(fp.name), "Temporary file should exist within the context."
        assert os.path.exists(
            fp.name
        ), "Temporary file should exist outside of context if cleanup=False."
        os.unlink(fp.name)

    def test_temporary_file_within_other_dir(self) -> None:
        with temporary_dir() as path:
            with temporary_file(root_dir=path) as f:
                assert os.path.realpath(f.name).startswith(
                    os.path.realpath(path)
                ), "file should be created in root_dir if specified."

    def test_temporary_dir_no_args(self) -> None:
        with temporary_dir() as path:
            assert os.path.exists(path), "Temporary dir should exist within the context."
            assert os.path.isdir(path), "Temporary dir should be a dir and not a file."
        assert not os.path.exists(path), "Temporary dir should not exist outside of the context."

    def test_temporary_dir_without_cleanup(self) -> None:
        with temporary_dir(cleanup=False) as path:
            assert os.path.exists(path), "Temporary dir should exist within the context."
        assert os.path.exists(
            path
        ), "Temporary dir should exist outside of context if cleanup=False."
        shutil.rmtree(path)

    def test_temporary_dir_with_root_dir(self) -> None:
        with temporary_dir() as path1:
            with temporary_dir(root_dir=path1) as path2:
                assert os.path.realpath(path2).startswith(
                    os.path.realpath(path1)
                ), "Nested temporary dir should be created within outer dir."

    def test_open_zipDefault(self) -> None:
        with temporary_dir() as tempdir:
            with open_zip(os.path.join(tempdir, "test"), "w") as zf:
                assert zf._allowZip64  # type: ignore[attr-defined] # intended to fail type check

    def test_open_zipTrue(self) -> None:
        with temporary_dir() as tempdir:
            with open_zip(os.path.join(tempdir, "test"), "w", allowZip64=True) as zf:
                assert zf._allowZip64  # type: ignore[attr-defined] # intended to fail type check

    def test_open_zipFalse(self) -> None:
        with temporary_dir() as tempdir:
            with open_zip(os.path.join(tempdir, "test"), "w", allowZip64=False) as zf:
                assert not zf._allowZip64  # type: ignore[attr-defined] # intended to fail type check

    def test_open_zip_raises_exception_on_falsey_paths(self):
        falsey = (None, "", False)
        for invalid in falsey:
            with pytest.raises(InvalidZipPath), open_zip(invalid):
                pass

    def test_open_zip_returns_realpath_on_badzipfile(self) -> None:
        # In case of file corruption, deleting a Pants-constructed symlink would not resolve the error.
        with temporary_file() as not_zip:
            with temporary_dir() as tempdir:
                file_symlink = os.path.join(tempdir, "foo")
                os.symlink(not_zip.name, file_symlink)
                assert os.path.realpath(file_symlink) == os.path.realpath(not_zip.name)
                with pytest.raises(zipfile.BadZipfile, match=f"{not_zip.name}"), open_zip(
                    file_symlink
                ):
                    pass

    def test_permissions(self) -> None:
        with temporary_file(permissions=0o700) as f:
            assert 0o700 == os.stat(f.name)[0] & 0o777

        with temporary_dir(permissions=0o644) as path:
            assert 0o644 == os.stat(path)[0] & 0o777
