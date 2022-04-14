# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.lint.black.skip_field import SkipBlackField
from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import InterpreterConstraintsField, PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.fmt import FmtRequest, FmtResult
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.selectors import MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class BlackFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipBlackField).value


class BlackRequest(FmtRequest):
    field_set_type = BlackFieldSet
    name = Black.options_scope


@rule(desc="Format with Black", level=LogLevel.DEBUG)
async def black_fmt(request: BlackRequest, black: Black, python_setup: PythonSetup) -> FmtResult:
    if black.skip:
        return FmtResult.skip(formatter_name=request.name)
    # Black requires 3.6+ but uses the typed-ast library to work with 2.7, 3.4, 3.5, 3.6, and 3.7.
    # However, typed-ast does not understand 3.8+, so instead we must run Black with Python 3.8+
    # when relevant. We only do this if if <3.8 can't be used, as we don't want a loose requirement
    # like `>=3.6` to result in requiring Python 3.8, which would error if 3.8 is not installed on
    # the machine.
    all_interpreter_constraints = InterpreterConstraints.create_from_compatibility_fields(
        (field_set.interpreter_constraints for field_set in request.field_sets),
        python_setup,
    )
    tool_interpreter_constraints = (
        all_interpreter_constraints
        if (
            black.options.is_default("interpreter_constraints")
            and all_interpreter_constraints.requires_python38_or_newer(
                python_setup.interpreter_universe
            )
        )
        else black.interpreter_constraints
    )

    black_pex_get = Get(
        VenvPex,
        PexRequest,
        black.to_pex_request(interpreter_constraints=tool_interpreter_constraints),
    )
    config_files_get = Get(
        ConfigFiles, ConfigFilesRequest, black.config_request(request.snapshot.dirs)
    )

    black_pex, config_files = await MultiGet(black_pex_get, config_files_get)

    input_digest = await Get(
        Digest, MergeDigests((request.snapshot.digest, config_files.snapshot.digest))
    )

    result = await Get(
        ProcessResult,
        VenvPexProcess(
            black_pex,
            argv=(
                *(("--config", black.config) if black.config else ()),
                "-W",
                "{pants_concurrency}",
                *black.args,
                *request.snapshot.files,
            ),
            input_digest=input_digest,
            output_files=request.snapshot.files,
            concurrency_available=len(request.field_sets),
            description=f"Run Black on {pluralize(len(request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult.create(request, result, output_snapshot, strip_chroot_path=True)


def rules():
    return [
        *collect_rules(),
        UnionRule(FmtRequest, BlackRequest),
        *pex.rules(),
    ]
