# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.core.goals.export import ExportError, ExportRequest, ExportResult, ExportResults, Symlink
from pants.core.util_rules.distdir import DistDir
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.util.docutil import bin_name
from pants.util.strutil import path_safe

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportVenvsRequest(ExportRequest):
    pass


@dataclass(frozen=True)
class _ExportVenvRequest(EngineAwareParameter):
    resolve: str
    root_python_targets: tuple[Target, ...]

    def debug_hint(self) -> str:
        return self.resolve


@rule
async def export_virtualenv(
    request: _ExportVenvRequest, python_setup: PythonSetup, pex_env: PexEnvironment
) -> ExportResult:
    interpreter_constraints = InterpreterConstraints(
        python_setup.resolves_to_interpreter_constraints.get(
            request.resolve, python_setup.interpreter_constraints
        )
    )
    min_interpreter = interpreter_constraints.snap_to_minimum(python_setup.interpreter_universe)
    if not min_interpreter:
        raise ExportError(
            f"The resolve '{request.resolve}' (from `[python].resolves`) has invalid interpreter "
            f"constraints, which are set via `[python].resolves_to_interpreter_constraints`: "
            f"{interpreter_constraints}. Could not determine the minimum compatible interpreter."
        )

    venv_pex = await Get(
        VenvPex,
        RequirementsPexRequest(
            (tgt.address for tgt in request.root_python_targets),
            internal_only=True,
            hardcoded_interpreter_constraints=min_interpreter,
        ),
    )

    complete_pex_env = pex_env.in_workspace()
    venv_abspath = os.path.join(complete_pex_env.pex_root, venv_pex.venv_rel_dir)

    # Run the venv_pex to get the full python version (including patch #), so we
    # can use it in the symlink name.
    res = await Get(
        ProcessResult,
        VenvPexProcess(
            venv_pex=venv_pex,
            description="Create virtualenv",
            argv=["-c", "import sys; print('.'.join(str(x) for x in sys.version_info[0:3]))"],
            input_digest=venv_pex.digest,
        ),
    )
    py_version = res.stdout.strip().decode()

    return ExportResult(
        f"virtualenv for the resolve '{request.resolve}' (using {min_interpreter})",
        os.path.join("python", "virtualenvs", path_safe(request.resolve)),
        symlinks=[Symlink(venv_abspath, py_version)],
    )


@rule
async def export_virtualenvs(
    request: ExportVenvsRequest, python_setup: PythonSetup, dist_dir: DistDir
) -> ExportResults:
    resolve_to_root_targets: DefaultDict[str, list[Target]] = defaultdict(list)
    for tgt in request.targets:
        if not tgt.has_field(PythonResolveField):
            continue
        resolve = tgt[PythonResolveField].normalized_value(python_setup)
        resolve_to_root_targets[resolve].append(tgt)

    venvs = await MultiGet(
        Get(
            ExportResult,
            _ExportVenvRequest(
                resolve if resolve != "<ignore>" else python_setup.default_resolve, tuple(tgts)
            ),
        )
        for resolve, tgts in resolve_to_root_targets.items()
    )

    deprecated_path = dist_dir.relpath / "python" / "virtualenv"
    if venvs and deprecated_path.exists():
        logger.warning(
            f"`{bin_name()} export ::` no longer writes virtualenvs to {deprecated_path}, but "
            f"instead underneath {dist_dir.relpath / 'python' / 'virtualenvs'}. You will need to "
            "update your IDE to point to the new virtualenv.\n\n"
            f"To silence this error, delete {deprecated_path}"
        )

    return ExportResults(venvs)


def rules():
    return [
        *collect_rules(),
        UnionRule(ExportRequest, ExportVenvsRequest),
    ]
