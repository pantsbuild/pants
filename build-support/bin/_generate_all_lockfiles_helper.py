# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Ensure that we generate interpreter constraints using the correct values.

This is necessary because the tool lockfiles we generate are used as the default for all Pants
users. We need to decouple our own internal usage (e.g. using Flake8 plugins) from what the default
should be.
"""

import logging
import subprocess

from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import PythonProtobufMypyPlugin
from pants.backend.docker.subsystems.dockerfile_parser import DockerfileParser
from pants.backend.python.goals.coverage_py import CoverageSubsystem
from pants.backend.python.lint.autoflake.subsystem import Autoflake
from pants.backend.python.lint.bandit.subsystem import Bandit
from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.docformatter.subsystem import Docformatter
from pants.backend.python.lint.flake8.subsystem import Flake8
from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.lint.pylint.subsystem import Pylint
from pants.backend.python.lint.pyupgrade.subsystem import PyUpgrade
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.subsystems.ipython import IPython
from pants.backend.python.subsystems.lambdex import Lambdex
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.subsystems.setuptools import Setuptools
from pants.backend.python.subsystems.twine import TwineSubsystem
from pants.backend.python.typecheck.mypy.subsystem import MyPy
from pants.backend.terraform.dependency_inference import TerraformHcl2Parser

logger = logging.getLogger(__name__)


def main() -> None:
    # First, generate what we internally use.
    logger.info("First, generating lockfiles for internal usage")
    subprocess.run(
        [
            "./pants",
            "--concurrent",
            "--tag=-lockfile_ignore",
            # `generate_all_lockfiles.sh` will have overridden this option to solve the chicken
            # and egg problem from https://github.com/pantsbuild/pants/issues/12457. We must
            # restore it here so that the lockfile gets generated properly.
            "--python-experimental-lockfile=3rdparty/python/lockfiles/user_reqs.txt",
            "generate-lockfiles",
            "generate-user-lockfile",
            "::",
        ],
        check=True,
    )

    logger.info("Now, generating default tool lockfiles for users")
    # Now, generate default tool lockfiles. We must be careful that our own internal settings
    # (e.g. custom extra requirements) do not mess up the defaults.
    subprocess.run(
        [
            "./pants",
            "--concurrent",
            f"--python-interpreter-constraints={repr(PythonSetup.default_interpreter_constraints)}",
            # Autoflake.
            f"--autoflake-version={Autoflake.default_version}",
            f"--autoflake-extra-requirements={repr(Autoflake.default_extra_requirements)}",
            f"--autoflake-interpreter-constraints={repr(Autoflake.default_interpreter_constraints)}",
            f"--autoflake-lockfile={Autoflake.default_lockfile_path}",
            # Bandit.
            "--backend-packages=+['pants.backend.python.lint.bandit']",
            f"--bandit-version={Bandit.default_version}",
            f"--bandit-extra-requirements={repr(Bandit.default_extra_requirements)}",
            f"--bandit-lockfile={Bandit.default_lockfile_path}",
            # Black.
            f"--black-version={Black.default_version}",
            f"--black-extra-requirements={repr(Black.default_extra_requirements)}",
            f"--black-interpreter-constraints={repr(Black.default_interpreter_constraints)}",
            f"--black-lockfile={Black.default_lockfile_path}",
            # Docformatter.
            f"--docformatter-version={Docformatter.default_version}",
            f"--docformatter-extra-requirements={repr(Docformatter.default_extra_requirements)}",
            f"--docformatter-interpreter-constraints={repr(Docformatter.default_interpreter_constraints)}",
            f"--docformatter-lockfile={Docformatter.default_lockfile_path}",
            # Flake8.
            f"--flake8-version={Flake8.default_version}",
            f"--flake8-extra-requirements={repr(Flake8.default_extra_requirements)}",
            f"--flake8-lockfile={Flake8.default_lockfile_path}",
            # Isort.
            f"--isort-version={Isort.default_version}",
            f"--isort-extra-requirements={repr(Isort.default_extra_requirements)}",
            f"--isort-interpreter-constraints={repr(Isort.default_interpreter_constraints)}",
            f"--isort-lockfile={Isort.default_lockfile_path}",
            # Pylint.
            "--backend-packages=+['pants.backend.python.lint.pylint']",
            f"--pylint-version={Pylint.default_version}",
            f"--pylint-extra-requirements={repr(Pylint.default_extra_requirements)}",
            "--pylint-source-plugins=[]",
            f"--pylint-lockfile={Pylint.default_lockfile_path}",
            # Yapf.
            "--backend-packages=+['pants.backend.python.lint.yapf']",
            f"--yapf-version={Yapf.default_version}",
            f"--yapf-extra-requirements={repr(Yapf.default_extra_requirements)}",
            f"--yapf-interpreter-constraints={repr(Yapf.default_interpreter_constraints)}",
            f"--yapf-lockfile={Yapf.default_lockfile_path}",
            # PyUpgrade.
            "--backend-packages=+['pants.backend.experimental.python.lint.pyupgrade']",
            f"--pyupgrade-version={PyUpgrade.default_version}",
            f"--pyupgrade-extra-requirements={repr(PyUpgrade.default_extra_requirements)}",
            f"--pyupgrade-interpreter-constraints={repr(PyUpgrade.default_interpreter_constraints)}",
            f"--pyupgrade-lockfile={PyUpgrade.default_lockfile_path}",
            # IPython.
            f"--ipython-version={IPython.default_version}",
            f"--ipython-extra-requirements={repr(IPython.default_extra_requirements)}",
            f"--ipython-lockfile={IPython.default_lockfile_path}",
            # Setuptools.
            f"--setuptools-version={Setuptools.default_version}",
            f"--setuptools-extra-requirements={repr(Setuptools.default_extra_requirements)}",
            f"--setuptools-lockfile={Setuptools.default_lockfile_path}",
            # MyPy.
            f"--mypy-version={MyPy.default_version}",
            f"--mypy-extra-requirements={repr(MyPy.default_extra_requirements)}",
            "--mypy-source-plugins=[]",
            f"--mypy-interpreter-constraints={repr(MyPy.default_interpreter_constraints)}",
            f"--mypy-lockfile={MyPy.default_lockfile_path}",
            # MyPy Protobuf.
            "--backend-packages=+['pants.backend.codegen.protobuf.python']",
            f"--mypy-protobuf-version={PythonProtobufMypyPlugin.default_version}",
            f"--mypy-protobuf-extra-requirements={repr(PythonProtobufMypyPlugin.default_extra_requirements)}",
            f"--mypy-protobuf-interpreter-constraints={repr(PythonProtobufMypyPlugin.default_interpreter_constraints)}",
            f"--mypy-protobuf-lockfile={PythonProtobufMypyPlugin.default_lockfile_path}",
            # Lambdex.
            "--backend-packages=+['pants.backend.google_cloud_function.python','pants.backend.awslambda.python']",
            f"--lambdex-version={Lambdex.default_version}",
            f"--lambdex-extra-requirements={repr(Lambdex.default_extra_requirements)}",
            f"--lambdex-interpreter-constraints={repr(Lambdex.default_interpreter_constraints)}",
            f"--lambdex-lockfile={Lambdex.default_lockfile_path}",
            # Pytest
            f"--pytest-version={PyTest.default_version}",
            f"--pytest-extra-requirements={repr(PyTest.default_extra_requirements)}",
            f"--pytest-lockfile={PyTest.default_lockfile_path}",
            # Coverage.py
            f"--coverage-py-version={CoverageSubsystem.default_version}",
            f"--coverage-py-extra-requirements={repr(CoverageSubsystem.default_extra_requirements)}",
            f"--coverage-py-interpreter-constraints={repr(CoverageSubsystem.default_interpreter_constraints)}",
            f"--coverage-py-lockfile={CoverageSubsystem.default_lockfile_path}",
            # HCL2 for Terraform dependency inference
            "--backend-packages=+['pants.backend.experimental.terraform']",
            f"--terraform-hcl2-parser-version={TerraformHcl2Parser.default_version}",
            f"--terraform-hcl2-parser-extra-requirements={repr(TerraformHcl2Parser.default_extra_requirements)}",
            f"--terraform-hcl2-parser-interpreter-constraints={repr(TerraformHcl2Parser.default_interpreter_constraints)}",
            f"--terraform-hcl2-parser-lockfile={TerraformHcl2Parser.default_lockfile_path}",
            # Dockerfile parser for Docker dependency inference
            "--backend-packages=+['pants.backend.experimental.docker']",
            f"--dockerfile-parser-version={DockerfileParser.default_version}",
            f"--dockerfile-parser-extra-requirements={repr(DockerfileParser.default_extra_requirements)}",
            f"--dockerfile-parser-interpreter-constraints={repr(DockerfileParser.default_interpreter_constraints)}",
            f"--dockerfile-parser-lockfile={DockerfileParser.default_lockfile_path}",
            # Twine.
            f"--twine-version={TwineSubsystem.default_version}",
            f"--twine-extra-requirements={repr(TwineSubsystem.default_extra_requirements)}",
            f"--twine-interpreter-constraints={repr(TwineSubsystem.default_interpreter_constraints)}",
            f"--twine-lockfile={TwineSubsystem.default_lockfile_path}",
            # Run the goal.
            "generate-lockfiles",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
