# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Support for Python.

See https://www.pantsbuild.org/docs/python-backend.
"""

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.goals import (
    coverage_py,
    export,
    lockfile,
    package_pex_binary,
    pytest_runner,
    repl,
    run_pex_binary,
    run_python_source,
    setup_py,
    tailor,
)
from pants.backend.python.macros import (
    pipenv_requirements,
    poetry_requirements,
    python_requirements,
)
from pants.backend.python.macros.pipenv_requirements import PipenvRequirementsTargetGenerator
from pants.backend.python.macros.poetry_requirements import PoetryRequirementsTargetGenerator
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.macros.python_requirements import PythonRequirementsTargetGenerator
from pants.backend.python.subsystems import debugpy, ipython, pytest, python_native_code, setuptools
from pants.backend.python.target_types import (
    PexBinariesGeneratorTarget,
    PexBinary,
    PythonDistribution,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
    PythonTestUtilsGeneratorTarget,
)
from pants.backend.python.util_rules import (
    ancestor_files,
    local_dists,
    pex,
    pex_cli,
    pex_environment,
    pex_from_targets,
    python_sources,
)
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.target_types import TargetGeneratorSourcesHelperTarget


def build_file_aliases():
    return BuildFileAliases(objects={"python_artifact": PythonArtifact, "setup_py": PythonArtifact})


def rules():
    return (
        *ancestor_files.rules(),
        *coverage_py.rules(),
        *debugpy.rules(),
        *dependency_inference_rules.rules(),
        *export.rules(),
        *ipython.rules(),
        *local_dists.rules(),
        *lockfile.rules(),
        *package_pex_binary.rules(),
        *pex.rules(),
        *pex_cli.rules(),
        *pex_environment.rules(),
        *pex_from_targets.rules(),
        *pytest.rules(),
        *pytest_runner.rules(),
        *python_native_code.rules(),
        *python_sources.rules(),
        *repl.rules(),
        *run_pex_binary.rules(),
        *run_python_source.rules(),
        *setup_py.rules(),
        *setuptools.rules(),
        *tailor.rules(),
        *target_types_rules.rules(),
        # Macros.
        *pipenv_requirements.rules(),
        *poetry_requirements.rules(),
        *python_requirements.rules(),
    )


def target_types():
    return (
        PexBinary,
        PexBinariesGeneratorTarget,
        PythonDistribution,
        TargetGeneratorSourcesHelperTarget,
        PythonRequirementTarget,
        PythonSourcesGeneratorTarget,
        PythonSourceTarget,
        PythonTestsGeneratorTarget,
        PythonTestTarget,
        PythonTestUtilsGeneratorTarget,
        # Macros.
        PipenvRequirementsTargetGenerator,
        PoetryRequirementsTargetGenerator,
        PythonRequirementsTargetGenerator,
    )
