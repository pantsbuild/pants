# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript, EntryPoint
from pants.backend.python.util_rules.pex import VenvPex, create_venv_pex
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.intrinsics import create_digest
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.util.logging import LogLevel
from pants.util.resources import read_resource
from pants.util.strutil import help_text

_ELFDEPS_PACKAGE = "pants.backend.nfpm.native_libs.elfdeps"
_ANALYZE_WHEELS_SCRIPT = "analyze_wheels.py"
_ANALYZE_WHEELS_TOOL = "__pants_elfdeps_analyze_wheels.py"


class Elfdeps(PythonToolBase):
    options_scope = "elfdeps"
    help_short = help_text(
        """
        Used to analyze ELF binaries.

        Both elfdeps and pyelftools (used by elfdeps) are pure-python libraries,
        so this should be portable across platforms.
        """
    )

    default_main = ConsoleScript("elfdeps")
    default_requirements = ["elfdeps>=0.2.0"]

    default_interpreter_constraints = ["CPython>=3.10,<4"]
    register_interpreter_constraints = True

    default_lockfile_resource = (_ELFDEPS_PACKAGE, "elfdeps.lock")


@dataclass(frozen=True)
class ElfdepsAnalyzeWheelsTool:
    pex: VenvPex


@rule(desc=f"Setup elfdeps/{_ANALYZE_WHEELS_SCRIPT}", level=LogLevel.DEBUG)
async def setup_elfdeps_analyze_wheels_tool(
    _elfdeps: Elfdeps,
) -> ElfdepsAnalyzeWheelsTool:
    analyze_wheels_script = read_resource(_ELFDEPS_PACKAGE, _ANALYZE_WHEELS_SCRIPT)
    if not analyze_wheels_script:
        raise ValueError(
            f"Unable to find source of {_ANALYZE_WHEELS_SCRIPT!r} in {_ELFDEPS_PACKAGE}"
        )

    analyze_wheels_script_content = FileContent(
        path=_ANALYZE_WHEELS_TOOL, content=analyze_wheels_script, is_executable=True
    )
    analyze_wheels_script_digest = await create_digest(
        CreateDigest([analyze_wheels_script_content])
    )

    analyze_wheels_pex = await create_venv_pex(
        **implicitly(
            _elfdeps.to_pex_request(
                main=EntryPoint(PurePath(analyze_wheels_script_content.path).stem),
                sources=analyze_wheels_script_digest,
            )
        )
    )
    return ElfdepsAnalyzeWheelsTool(analyze_wheels_pex)


def rules() -> Iterable[Rule]:
    return collect_rules()
