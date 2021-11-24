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
    setup_py,
    tailor,
)
from pants.backend.python.macros.pants_requirement_caof import PantsRequirementCAOF
from pants.backend.python.macros.pipenv_requirements_caof import PipenvRequirementsCAOF
from pants.backend.python.macros.poetry_requirements_caof import PoetryRequirementsCAOF
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.macros.python_requirements_caof import PythonRequirementsCAOF
from pants.backend.python.subsystems import ipython, pytest, python_native_code, setuptools
from pants.backend.python.target_types import (
    PexBinary,
    PythonDistribution,
    PythonRequirementsFile,
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


def build_file_aliases():
    return BuildFileAliases(
        objects={"python_artifact": PythonArtifact, "setup_py": PythonArtifact},
        context_aware_object_factories={
            "python_requirements": PythonRequirementsCAOF,
            "poetry_requirements": PoetryRequirementsCAOF,
            "pipenv_requirements": PipenvRequirementsCAOF,
            PantsRequirementCAOF.alias: PantsRequirementCAOF,
        },
    )


def rules():
    return (
        *ancestor_files.rules(),
        *coverage_py.rules(),
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
        *setup_py.rules(),
        *setuptools.rules(),
        *tailor.rules(),
        *target_types_rules.rules(),
    )


def target_types():
    return [
        PexBinary,
        PythonDistribution,
        PythonRequirementsFile,
        PythonRequirementTarget,
        PythonSourcesGeneratorTarget,
        PythonSourceTarget,
        PythonTestsGeneratorTarget,
        PythonTestTarget,
        PythonTestUtilsGeneratorTarget,
    ]
