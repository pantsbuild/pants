# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.pex_info import PexInfo

from pants.testutil.interpreter_selection_utils import (
    PY_3,
    PY_27,
    python_interpreter_path,
    skip_unless_python3_present,
    skip_unless_python27_and_python3_present,
    skip_unless_python27_present,
)
from pants.testutil.pants_run_integration_test import (
    PantsResult,
    PantsRunIntegrationTest,
    ensure_daemon,
)
from pants.testutil.pexrc_util import setup_pexrc_with_pex_python_path
from pants.util.contextutil import temporary_dir


class PythonRunIntegrationTest(PantsRunIntegrationTest):
    testproject = "testprojects/src/python/interpreter_selection"
    py2_interpreter_constraint = "CPython>=2.7,<3"
    py3_interpreter_constraint = "CPython>=3.6"

    @classmethod
    def hermetic(cls):
        return True

    def run_pants(
        self, command, config=None, stdin_data=None, extra_env=None, cleanup_workdir=True, **kwargs
    ) -> PantsResult:
        config = config or {}
        source = config.get("source", {})
        config["source"] = source
        source["root_patterns"] = ["src/python"]
        return super().run_pants(command, config, stdin_data, extra_env, cleanup_workdir, **kwargs)

    @skip_unless_python3_present
    @ensure_daemon
    def test_run_3(self):
        self._run_version(PY_3)

    @skip_unless_python27_present
    @ensure_daemon
    def test_run_27(self):
        self._run_version(PY_27)

    def _run_version(self, version):
        echo = self._run_echo_version(version)
        v = echo.split(".")  # E.g., 2.7.13.
        self.assertTrue(len(v) > 2, f"Not a valid version string: {v}")
        expected_components = version.split(".")
        self.assertEqual(expected_components, v[: len(expected_components)])

    def _run_echo_version(self, version):
        binary_name = f"echo_interpreter_version_{version}"
        binary_target = f"{self.testproject}:{binary_name}"
        # Build a pex.
        # Avoid some known-to-choke-on interpreters.
        if version == PY_3:
            constraint = f'["{self.py3_interpreter_constraint}"]'
        else:
            constraint = f'["{self.py2_interpreter_constraint}"]'
        command = [
            "run",
            binary_target,
            f"--python-setup-interpreter-constraints={constraint}",
            "--quiet",
        ]
        pants_run = self.run_pants(command=command)
        return pants_run.stdout_data.splitlines()[0].strip()

    @skip_unless_python27_and_python3_present
    def test_run_27_and_then_3(self):
        with temporary_dir() as interpreters_cache:
            pants_ini_config = {"python-setup": {"interpreter_cache_dir": interpreters_cache}}
            pants_run_27 = self.run_pants(
                command=["run", f"{self.testproject}:echo_interpreter_version_2.7"],
                config=pants_ini_config,
            )
            self.assert_success(pants_run_27)
            pants_run_3 = self.run_pants(
                command=[
                    "run",
                    f"{self.testproject}:echo_interpreter_version_3",
                    f"--python-setup-interpreter-constraints={self.py2_interpreter_constraint}",
                    f"--python-setup-interpreter-constraints={self.py3_interpreter_constraint}",
                ],
                config=pants_ini_config,
            )
            self.assert_success(pants_run_3)

    @skip_unless_python3_present
    def test_run_3_by_option(self):
        with temporary_dir() as interpreters_cache:
            pants_ini_config = {
                "python-setup": {
                    "interpreter_constraints": [
                        f"{self.py2_interpreter_constraint}",
                        f"{self.py3_interpreter_constraint}",
                    ],
                    "interpreter_cache_dir": interpreters_cache,
                }
            }
            pants_run_3 = self.run_pants(
                command=[
                    "run",
                    f"{self.testproject}:echo_interpreter_version_3",
                    f'--python-setup-interpreter-constraints=["{self.py3_interpreter_constraint}"]',
                ],
                config=pants_ini_config,
            )
            self.assert_success(pants_run_3)

    @skip_unless_python27_present
    def test_run_2_by_option(self):
        with temporary_dir() as interpreters_cache:
            pants_ini_config = {
                "python-setup": {
                    "interpreter_constraints": [
                        f"{self.py2_interpreter_constraint}",
                        f"{self.py3_interpreter_constraint}",
                    ],
                    "interpreter_cache_dir": interpreters_cache,
                }
            }
            pants_run_2 = self.run_pants(
                command=[
                    "run",
                    f"{self.testproject}:echo_interpreter_version_2.7",
                    f'--python-setup-interpreter-constraints=["{self.py2_interpreter_constraint}"]',
                ],
                config=pants_ini_config,
            )
            self.assert_success(pants_run_2)

    def test_die(self):
        command = [
            "run",
            f"{self.testproject}:die",
            f'--python-setup-interpreter-constraints=["{self.py2_interpreter_constraint}", "{self.py3_interpreter_constraint}"]',
            "--quiet",
        ]
        pants_run = self.run_pants(command=command)
        assert pants_run.returncode == 57

    def test_get_env_var(self):
        var_key = "SOME_MAGICAL_VAR"
        var_val = "a value"
        command = ["-q", "run", "testprojects/src/python/print_env", "--", var_key]
        pants_run = self.run_pants(command=command, extra_env={var_key: var_val})
        self.assert_success(pants_run)
        self.assertEqual(var_val, pants_run.stdout_data.strip())

    @skip_unless_python27_and_python3_present
    def test_pants_run_interpreter_selection_with_pexrc(self):
        py27_path, py3_path = python_interpreter_path(PY_27), python_interpreter_path(PY_3)
        with setup_pexrc_with_pex_python_path([py27_path, py3_path]):
            with temporary_dir() as interpreters_cache:
                pants_ini_config = {"python-setup": {"interpreter_cache_dir": interpreters_cache}}
                pants_run_27 = self.run_pants(
                    command=[
                        "run",
                        "{}:main_py2".format(
                            os.path.join(self.testproject, "python_3_selection_testing")
                        ),
                    ],
                    config=pants_ini_config,
                )
                self.assert_success(pants_run_27)
                self.assertIn("I am a python 2 library method.", pants_run_27.stdout_data)
                pants_run_3 = self.run_pants(
                    command=[
                        "run",
                        "{}:main_py3".format(
                            os.path.join(self.testproject, "python_3_selection_testing")
                        ),
                    ],
                    config=pants_ini_config,
                )
                self.assert_success(pants_run_3)
                self.assertIn("I am a python 3 library method.", pants_run_3.stdout_data)

    @skip_unless_python27_and_python3_present
    def test_pants_binary_interpreter_selection_with_pexrc(self):
        py27_path, py3_path = python_interpreter_path(PY_27), python_interpreter_path(PY_3)
        with setup_pexrc_with_pex_python_path([py27_path, py3_path]):
            with temporary_dir() as interpreters_cache:
                pants_ini_config = {"python-setup": {"interpreter_cache_dir": interpreters_cache}}
                pants_run_27 = self.run_pants(
                    command=[
                        "binary",
                        "{}:main_py2".format(
                            os.path.join(self.testproject, "python_3_selection_testing")
                        ),
                    ],
                    config=pants_ini_config,
                )
                self.assert_success(pants_run_27)
                pants_run_3 = self.run_pants(
                    command=[
                        "binary",
                        "{}:main_py3".format(
                            os.path.join(self.testproject, "python_3_selection_testing")
                        ),
                    ],
                    config=pants_ini_config,
                )
                self.assert_success(pants_run_3)

        # Ensure proper interpreter constraints were passed to built pexes.
        py2_pex = os.path.join(os.getcwd(), "dist", "main_py2.pex")
        py3_pex = os.path.join(os.getcwd(), "dist", "main_py3.pex")
        py2_info = PexInfo.from_pex(py2_pex)
        py3_info = PexInfo.from_pex(py3_pex)
        self.assertIn("CPython>2.7.6,<3", py2_info.interpreter_constraints)
        self.assertIn("CPython>3", py3_info.interpreter_constraints)

        # Cleanup created pexes.
        os.remove(py2_pex)
        os.remove(py3_pex)

    @skip_unless_python3_present
    def test_target_constraints_with_no_sources(self):
        with temporary_dir() as interpreters_cache:
            pants_config = {
                "python-setup": {
                    "interpreter_cache_dir": interpreters_cache,
                    "interpreter_constraints": ["CPython>3"],
                },
                "source": {"root_patterns": ["src/python"]},
            }
            # Run task.
            pants_run = self.run_pants(
                command=[
                    "run",
                    "{}:test_bin".format(
                        os.path.join(self.testproject, "test_target_with_no_sources")
                    ),
                ],
                config=pants_config,
            )
            self.assert_success(pants_run)
            self.assertIn("python3", pants_run.stdout_data)

            # Binary task.
            pants_run = self.run_pants(
                command=[
                    "binary",
                    "{}:test_bin".format(
                        os.path.join(self.testproject, "test_target_with_no_sources")
                    ),
                ],
                config=pants_config,
            )
            self.assert_success(pants_run)

        # Ensure proper interpreter constraints were passed to built pexes.
        py2_pex = os.path.join(os.getcwd(), "dist", "test_bin.pex")
        py2_info = PexInfo.from_pex(py2_pex)
        self.assertIn("CPython>3", py2_info.interpreter_constraints)
        # Cleanup.
        os.remove(py2_pex)
