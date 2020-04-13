# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class MypyIntegrationTest(PantsRunIntegrationTest):

    cmdline = ["--backend-packages=pants.contrib.mypy", "lint"]

    @classmethod
    def target(cls, name):
        return f"contrib/mypy/examples/src/python/simple:{name}"

    def test_valid_type_hints(self):
        result = self.run_pants([*self.cmdline, self.target("valid")])
        self.assert_success(result)

    def test_invalid_type_hints(self):
        result = self.run_pants([*self.cmdline, self.target("invalid")])
        self.assert_failure(result)


class MypyPluginIntegrationTest(PantsRunIntegrationTest):

    example_dir = Path("contrib/mypy/examples/src/python/mypy_plugin")

    @classmethod
    def cmdline(cls, *, include_requirements):
        cmd = [
            "--backend-packages=pants.contrib.mypy",
            f'--mypy-config={cls.example_dir / "mypy.ini"}',
            "--mypy-version=mypy==0.720",
            "lint.mypy",
        ]
        if include_requirements:
            cmd.append("--include-requirements")
        return cmd

    @classmethod
    def target(cls, name):
        return f"{cls.example_dir}:{name}"

    def test_valid_library_use_include_requirements(self):
        result = self.run_pants([*self.cmdline(include_requirements=True), self.target("valid")])
        self.assert_success(result)

    def test_invalid_library_use_include_requirements(self):
        result = self.run_pants([*self.cmdline(include_requirements=True), self.target("invalid")])
        self.assert_failure(result)

    def test_valid_library_use_exclude_requirements(self):
        # The target is valid, but we fail to include the mypy plugin and type information needed via
        # requirements and so the check fails.
        result = self.run_pants([*self.cmdline(include_requirements=False), self.target("valid")])
        self.assert_failure(result)
