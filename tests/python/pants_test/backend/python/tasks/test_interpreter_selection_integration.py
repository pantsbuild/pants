# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import os
import subprocess

from pex.executor import Executor
from pex.interpreter import PythonInterpreter

from pants.testutil.interpreter_selection_utils import (
    PY_3,
    PY_27,
    skip_unless_python3_present,
    skip_unless_python27_and_python3_present,
    skip_unless_python27_present,
)
from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


class InterpreterSelectionIntegrationTest(PantsRunIntegrationTest):

    testproject = "testprojects/src/python/interpreter_selection"

    @classmethod
    def hermetic(cls):
        # We must set as true to ignore `PANTS_PYTHON_SETUP_INTERPRETER_CONSTRAINTS`
        # preconfiguring the interpreter_constraint. For example, in `ci.py` we set
        # this environment variable to Python 3, which overrides any config defined
        # in the below tests.
        return True

    def _build_pex(self, binary_target, config=None, args=None, version=PY_27):
        # By default, Avoid some known-to-choke-on interpreters.
        constraint = '["CPython>=3.6"]' if version == PY_3 else '["CPython>=2.7,<3"]'
        args = (
            list(args)
            if args is not None
            else [f"--python-setup-interpreter-constraints={constraint}"]
        )
        command = ["binary", binary_target] + args
        return self.run_pants(command=command, config=config)

    def _echo_version(self, version):
        with temporary_dir() as distdir:
            config = {
                "GLOBAL": {"pants_distdir": distdir},
                "source": {"root_patterns": ["src/python"]},
            }
            binary_name = f"echo_interpreter_version_{version}"
            binary_target = f"{self.testproject}:{binary_name}"
            pants_run = self._build_pex(binary_target, config, version=version)
            self.assert_success(pants_run, f"Failed to build {binary_target}.")

            # Run the built pex.
            exe = os.path.join(distdir, binary_name + ".pex")
            return self._popen_stdout(exe)

    def _popen_stdout(self, exe):
        proc = subprocess.Popen([exe], stdout=subprocess.PIPE)
        (stdout_data, _) = proc.communicate()
        return stdout_data.decode()

    def _test_version(self, version):
        self._assert_version_matches(self._echo_version(version), version)

    def _assert_version_matches(self, actual, expected):
        v = actual.strip().split(".")  # E.g., 2.7.13.
        self.assertTrue(len(v) > 2, f"Not a valid version string: {v}")
        expected_components = expected.split(".")
        self.assertEqual(expected_components, v[: len(expected_components)])

    def test_cli_option_wins_compatibility_conflict(self):
        # Tests that targets with compatibility conflicts collide.
        binary_target = f"{self.testproject}:deliberately_conflicting_compatibility"
        pants_run = self._build_pex(binary_target)
        self.assert_success(pants_run, f"Failed to build {binary_target}.")

    def test_conflict_via_config(self):
        # Tests that targets with compatibility conflict with targets with default compatibility.
        # NB: Passes empty `args` to avoid having the default CLI args override the config.
        config = {"python-setup": {"interpreter_constraints": ["CPython<2.7"]}}
        binary_target = f"{self.testproject}:echo_interpreter_version"
        pants_run = self._build_pex(binary_target, config=config, args=[])
        self.assert_failure(pants_run, f"Unexpected successful build of {binary_target}.")
        self.assertIn(
            "Unable to detect a suitable interpreter for compatibilities", pants_run.stdout_data
        )
        self.assertIn(
            "CPython<2.7", pants_run.stdout_data, "Did not output requested compatibility."
        )
        self.assertIn(f"Conflicting targets: {binary_target}", pants_run.stdout_data)
        # NB: we expect the error message to print *all* interpreters resolved by Pants. However,
        # to simplify the tests and for hermicity, here we only test that the current interpreter
        # gets printed as a proxy for the overall behavior.
        self.assertIn(
            PythonInterpreter.get().version_string,
            pants_run.stdout_data,
            "Did not output interpreters discovered by Pants.",
        )

    @skip_unless_python27_and_python3_present
    def test_binary_uses_own_compatibility(self):
        """Tests that a binary target uses its own compatibility, rather than including that of its
        transitive dependencies."""
        # This target depends on a 2.7 minimum library, but does not declare its own compatibility.
        # By specifying a version on the CLI, we ensure that the binary target will use that, and then
        # test that it ends up with the version we request (and not the lower version specified on its
        # dependency).
        with temporary_dir() as distdir:
            config = {
                "GLOBAL": {"pants_distdir": distdir},
                "source": {"root_patterns": ["src/python"]},
            }
            args = [
                '--python-setup-interpreter-constraints=["CPython>=3.6"]',
            ]
            binary_name = "echo_interpreter_version"
            binary_target = f"{self.testproject}:{binary_name}"
            pants_run = self._build_pex(binary_target, config=config, args=args)
            self.assert_success(pants_run, f"Failed to build {binary_target}.")

            actual = self._popen_stdout(os.path.join(distdir, binary_name + ".pex"))
            self._assert_version_matches(actual, "3")

    @skip_unless_python3_present
    def test_select_3(self):
        self._test_version(PY_3)

    @skip_unless_python27_present
    def test_select_27(self):
        self._test_version(PY_27)

    def test_stale_interpreter_purge_integration(self):
        target = f"{self.testproject}:{'echo_interpreter_version'}"
        config = {
            "python-setup": {"interpreter_constraints": ["CPython>=2.7,<4"]},
            "source": {"root_patterns": ["src/python"]},
        }
        with self.temporary_workdir() as workdir:
            pants_run = self.run_pants_with_workdir(["run", target], workdir=workdir, config=config)
            self.assert_success(pants_run)

            def _prepend_bad_interpreter_to_interpreter_path_file(path):
                with open(path, "r") as fp:
                    file_data = fp.readlines()
                    file_data[0] = "/my/bogus/interpreter/python2.7"
                with open(path, "w") as fp:
                    fp.writelines(file_data)

            def _validate_good_interpreter_path_file(path):
                with open(path, "r") as fp:
                    lines = fp.readlines()
                    binary = lines[0].strip()
                    try:
                        interpreter = PythonInterpreter.from_binary(binary)
                        return True if interpreter else False
                    except Executor.ExecutableNotFound:
                        return False

            # Mangle interpreter.info.
            for path in glob.glob(os.path.join(workdir, "pyprep/interpreter/*/interpreter.info")):
                _prepend_bad_interpreter_to_interpreter_path_file(path)

            pants_run = self.run_pants_with_workdir(["run", target], workdir=workdir, config=config)
            self.assert_success(pants_run)
            for path in glob.glob(os.path.join(workdir, "pyprep/interpreter/*/interpreter.info")):
                self.assertTrue(
                    _validate_good_interpreter_path_file(path),
                    f"interpreter.info was not purged and repopulated properly: {path}",
                )
