# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Ensure that we generate interpreter constraints using the correct values.

This is necessary because the tool lockfiles we generate are used as the default for all Pants
users. We need to decouple our own internal usage (e.g. using Flake8 plugins) from what the default
should be.
"""

import logging
import shutil
import subprocess

from pants.backend.awslambda.python.lambdex import Lambdex
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import PythonProtobufMypyPlugin
from pants.backend.python.goals.coverage_py import CoverageSubsystem
from pants.backend.python.lint.bandit.subsystem import Bandit
from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.docformatter.subsystem import Docformatter
from pants.backend.python.lint.flake8.subsystem import Flake8
from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.lint.pylint.subsystem import Pylint
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.subsystems.ipython import IPython
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.setuptools import Setuptools
from pants.python.python_setup import PythonSetup

logger = logging.getLogger(__name__)


def validate_python_installed(binary: str) -> None:
    if not shutil.which(binary):
        raise Exception(
            f"Must have `{binary}` installed and discoverable to safely generate lockfiles."
        )


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
            "--python-setup-experimental-lockfile=3rdparty/python/lockfiles/user_reqs.txt",
            "lock",
            "tool-lock",
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
            f"--python-setup-interpreter-constraints={repr(PythonSetup.default_interpreter_constraints)}",
            # Bandit.
            "--backend-packages=+['pants.backend.python.lint.bandit']",
            f"--bandit-version={Bandit.default_version}",
            f"--bandit-extra-requirements={repr(Bandit.default_extra_requirements)}",
            f"--bandit-experimental-lockfile={Bandit.default_lockfile_path}",
            # Black.
            f"--black-version={Black.default_version}",
            f"--black-extra-requirements={repr(Black.default_extra_requirements)}",
            f"--black-interpreter-constraints={repr(Black.default_interpreter_constraints)}",
            f"--black-experimental-lockfile={Black.default_lockfile_path}",
            # Docformatter.
            f"--docformatter-version={Docformatter.default_version}",
            f"--docformatter-extra-requirements={repr(Docformatter.default_extra_requirements)}",
            f"--docformatter-interpreter-constraints={repr(Docformatter.default_interpreter_constraints)}",
            f"--docformatter-experimental-lockfile={Docformatter.default_lockfile_path}",
            # Flake8.
            f"--flake8-version={Flake8.default_version}",
            f"--flake8-extra-requirements={repr(Flake8.default_extra_requirements)}",
            f"--flake8-experimental-lockfile={Flake8.default_lockfile_path}",
            # Isort.
            f"--isort-version={Isort.default_version}",
            f"--isort-extra-requirements={repr(Isort.default_extra_requirements)}",
            f"--isort-interpreter-constraints={repr(Isort.default_interpreter_constraints)}",
            f"--isort-experimental-lockfile={Isort.default_lockfile_path}",
            # Pylint.
            "--backend-packages=+['pants.backend.python.lint.pylint']",
            f"--pylint-version={Pylint.default_version}",
            f"--pylint-extra-requirements={repr(Pylint.default_extra_requirements)}",
            f"--pylint-experimental-lockfile={Pylint.default_lockfile_path}",
            # Yapf.
            "--backend-packages=+['pants.backend.python.lint.yapf']",
            f"--yapf-version={Yapf.default_version}",
            f"--yapf-extra-requirements={repr(Yapf.default_extra_requirements)}",
            f"--yapf-interpreter-constraints={repr(Yapf.default_interpreter_constraints)}",
            f"--yapf-experimental-lockfile={Yapf.default_lockfile_path}",
            # IPython.
            f"--ipython-version={IPython.default_version}",
            f"--ipython-extra-requirements={repr(IPython.default_extra_requirements)}",
            f"--ipython-experimental-lockfile={IPython.default_lockfile_path}",
            # Setuptools.
            f"--setuptools-version={Setuptools.default_version}",
            f"--setuptools-extra-requirements={repr(Setuptools.default_extra_requirements)}",
            f"--setuptools-experimental-lockfile={Setuptools.default_lockfile_path}",
            # Python Protobuf MyPy plugin.
            "--backend-packages=+['pants.backend.codegen.protobuf.python']",
            f"--python-protobuf-mypy-plugin-version={PythonProtobufMypyPlugin.default_version}",
            f"--python-protobuf-mypy-plugin-extra-requirements={repr(PythonProtobufMypyPlugin.default_extra_requirements)}",
            f"--python-protobuf-mypy-plugin-interpreter-constraints={repr(PythonProtobufMypyPlugin.default_interpreter_constraints)}",
            f"--python-protobuf-mypy-plugin-experimental-lockfile={PythonProtobufMypyPlugin.default_lockfile_path}",
            # Lambdex.
            "--backend-packages=+['pants.backend.awslambda.python']",
            f"--lambdex-version={Lambdex.default_version}",
            f"--lambdex-extra-requirements={repr(Lambdex.default_extra_requirements)}",
            f"--lambdex-interpreter-constraints={repr(Lambdex.default_interpreter_constraints)}",
            f"--lambdex-experimental-lockfile={Lambdex.default_lockfile_path}",
            # Pytest
            f"--pytest-version={PyTest.default_version}",
            f"--pytest-extra-requirements={repr(PyTest.default_extra_requirements)}",
            f"--pytest-experimental-lockfile={PyTest.default_lockfile_path}",
            # Coverage.py
            f"--coverage-py-version={CoverageSubsystem.default_version}",
            f"--coverage-py-extra-requirements={repr(CoverageSubsystem.default_extra_requirements)}",
            f"--coverage-py-interpreter-constraints={repr(CoverageSubsystem.default_interpreter_constraints)}",
            f"--coverage-py-experimental-lockfile={CoverageSubsystem.default_lockfile_path}",
            # Run the goal.
            "tool-lock",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
