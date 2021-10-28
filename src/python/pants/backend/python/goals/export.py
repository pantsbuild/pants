# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.core.goals.export import ExportableData, ExportableDataRequest, ExportError, Symlink
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class ExportedVenvRequest(ExportableDataRequest):
    pass


@rule
async def export_venv(
    request: ExportedVenvRequest, python_setup: PythonSetup, pex_env: PexEnvironment
) -> ExportableData:
    # Pick a single interpreter for the venv.
    interpreter_constraints = InterpreterConstraints.create_from_targets(
        request.targets, python_setup
    )
    min_interpreter = interpreter_constraints.snap_to_minimum(python_setup.interpreter_universe)
    if not min_interpreter:
        raise ExportError(
            "There is no single Python interpreter compatible with all the "
            "targets for which export was requested. Please restrict the target set "
            "to one that shares a compatible interpreter."
        )

    venv_pex = await Get(
        VenvPex,
        PexFromTargetsRequest,
        PexFromTargetsRequest.for_requirements(
            (tgt.address for tgt in request.targets),
            internal_only=True,
            hardcoded_interpreter_constraints=min_interpreter,
        ),
    )

    complete_pex_env = pex_env.in_workspace()
    venv_abspath = os.path.join(complete_pex_env.pex_root, venv_pex.venv_rel_dir)

    # Run the venv_pex to ensure that the underlying venv is created if necessary.
    # We also use this to get the full python version (including patch #), so we
    # can use it in the symlink name (not critical, but nice to have).
    res = await Get(
        ProcessResult,
        VenvPexProcess(
            venv_pex=venv_pex,
            description="Create virtualenv",
            argv=["-c", "import sys; print('.'.join(str(x) for x in sys.version_info[0:3]))"],
            input_digest=venv_pex.digest,
            # TODO: Is there always a python_configured?
            extra_env=complete_pex_env.environment_dict(python_configured=True),
        ),
    )
    py_version = res.stdout.strip().decode()

    return ExportableData(
        f"virtualenv for {min_interpreter}",
        os.path.join("python", "virtualenv"),
        symlinks=[Symlink(venv_abspath, py_version)],
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(ExportableDataRequest, ExportedVenvRequest),
    ]
