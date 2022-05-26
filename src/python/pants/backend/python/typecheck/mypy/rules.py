# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.typecheck.mypy.skip_field import SkipMyPyField
from pants.backend.python.typecheck.mypy.subsystem import (
    MyPy,
    MyPyConfigFile,
    MyPyFirstPartyPlugins,
)
from pants.backend.python.util_rules import partition, pex_from_targets
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.check import REPORT_DIR, CheckRequest, CheckResult, CheckResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.collection import Collection
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests, RemovePrefix
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTargets, FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class MyPyFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    sources: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipMyPyField).value


@dataclass(frozen=True)
class MyPyPartition:
    root_field_sets: FrozenOrderedSet[MyPyFieldSet]
    closure: FrozenOrderedSet[Target]
    resolve_description: str | None
    interpreter_constraints: InterpreterConstraints

    def description(self) -> str:
        ics = str(sorted(str(c) for c in self.interpreter_constraints))
        return f"{self.resolve_description}, {ics}" if self.resolve_description else ics


class MyPyPartitions(Collection[MyPyPartition]):
    pass


class MyPyRequest(CheckRequest):
    field_set_type = MyPyFieldSet
    name = MyPy.options_scope


def generate_argv(
    mypy: MyPy,
    *,
    venv_python: str,
    file_list_path: str,
    python_version: Optional[str],
) -> Tuple[str, ...]:
    args = [f"--python-executable={venv_python}", *mypy.args]
    if mypy.config:
        args.append(f"--config-file={mypy.config}")
    if python_version:
        args.append(f"--python-version={python_version}")
    args.append(f"@{file_list_path}")
    return tuple(args)


def determine_python_files(files: Iterable[str]) -> Tuple[str, ...]:
    """We run over all .py and .pyi files, but .pyi files take precedence.

    MyPy will error if we say to run over the same module with both its .py and .pyi files, so we
    must be careful to only use the .pyi stub.
    """
    result: OrderedSet[str] = OrderedSet()
    for f in files:
        if f.endswith(".pyi"):
            py_file = f[:-1]  # That is, strip the `.pyi` suffix to be `.py`.
            result.discard(py_file)
            result.add(f)
        elif f.endswith(".py"):
            pyi_file = f + "i"
            if pyi_file not in result:
                result.add(f)
    return tuple(result)


@rule
async def mypy_typecheck_partition(
    partition: MyPyPartition,
    config_file: MyPyConfigFile,
    first_party_plugins: MyPyFirstPartyPlugins,
    mypy: MyPy,
    python_setup: PythonSetup,
) -> CheckResult:
    # MyPy requires 3.5+ to run, but uses the typed-ast library to work with 2.7, 3.4, 3.5, 3.6,
    # and 3.7. However, typed-ast does not understand 3.8+, so instead we must run MyPy with
    # Python 3.8+ when relevant. We only do this if <3.8 can't be used, as we don't want a
    # loose requirement like `>=3.6` to result in requiring Python 3.8+, which would error if
    # 3.8+ is not installed on the machine.
    tool_interpreter_constraints = (
        partition.interpreter_constraints
        if (
            mypy.options.is_default("interpreter_constraints")
            and partition.interpreter_constraints.requires_python38_or_newer(
                python_setup.interpreter_universe
            )
        )
        else mypy.interpreter_constraints
    )

    closure_sources_get = Get(PythonSourceFiles, PythonSourceFilesRequest(partition.closure))
    roots_sources_get = Get(
        SourceFiles,
        SourceFilesRequest(fs.sources for fs in partition.root_field_sets),
    )

    # See `requirements_venv_pex` for how this will get wrapped in a `VenvPex`.
    requirements_pex_get = Get(
        Pex,
        RequirementsPexRequest(
            (fs.address for fs in partition.root_field_sets),
            hardcoded_interpreter_constraints=partition.interpreter_constraints,
        ),
    )
    extra_type_stubs_pex_get = Get(
        Pex,
        PexRequest(
            output_filename="extra_type_stubs.pex",
            internal_only=True,
            requirements=PexRequirements(mypy.extra_type_stubs),
            interpreter_constraints=partition.interpreter_constraints,
        ),
    )

    mypy_pex_get = Get(
        VenvPex,
        PexRequest,
        mypy.to_pex_request(
            interpreter_constraints=tool_interpreter_constraints,
            extra_requirements=first_party_plugins.requirement_strings,
        ),
    )

    (
        closure_sources,
        roots_sources,
        mypy_pex,
        extra_type_stubs_pex,
        requirements_pex,
    ) = await MultiGet(
        closure_sources_get,
        roots_sources_get,
        mypy_pex_get,
        extra_type_stubs_pex_get,
        requirements_pex_get,
    )

    python_files = determine_python_files(roots_sources.snapshot.files)
    file_list_path = "__files.txt"
    file_list_digest_request = Get(
        Digest,
        CreateDigest([FileContent(file_list_path, "\n".join(python_files).encode())]),
    )

    # This creates a venv with all the 3rd-party requirements used by the code. We tell MyPy to
    # use this venv by setting `--python-executable`. Note that this Python interpreter is
    # different than what we run MyPy with.
    #
    # We could have directly asked the `PexFromTargetsRequest` to return a `VenvPex`, rather than
    # `Pex`, but that would mean missing out on sharing a cache with other goals like `test` and
    # `run`.
    requirements_venv_pex_request = Get(
        VenvPex,
        PexRequest(
            output_filename="requirements_venv.pex",
            internal_only=True,
            pex_path=[requirements_pex, extra_type_stubs_pex],
            interpreter_constraints=partition.interpreter_constraints,
        ),
    )

    requirements_venv_pex, file_list_digest = await MultiGet(
        requirements_venv_pex_request, file_list_digest_request
    )

    merged_input_files = await Get(
        Digest,
        MergeDigests(
            [
                file_list_digest,
                first_party_plugins.sources_digest,
                closure_sources.source_files.snapshot.digest,
                requirements_venv_pex.digest,
                config_file.digest,
            ]
        ),
    )

    all_used_source_roots = sorted(
        set(itertools.chain(first_party_plugins.source_roots, closure_sources.source_roots))
    )
    env = {
        "PEX_EXTRA_SYS_PATH": ":".join(all_used_source_roots),
        "MYPYPATH": ":".join(all_used_source_roots),
    }

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            mypy_pex,
            argv=generate_argv(
                mypy,
                venv_python=requirements_venv_pex.python.argv0,
                file_list_path=file_list_path,
                python_version=config_file.python_version_to_autoset(
                    partition.interpreter_constraints, python_setup.interpreter_universe
                ),
            ),
            input_digest=merged_input_files,
            extra_env=env,
            output_directories=(REPORT_DIR,),
            description=f"Run MyPy on {pluralize(len(python_files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    report = await Get(Digest, RemovePrefix(result.output_digest, REPORT_DIR))
    return CheckResult.from_fallible_process_result(
        result,
        partition_description=str(sorted(str(c) for c in partition.interpreter_constraints)),
        report=report,
    )


@rule(desc="Determine if necessary to partition MyPy input", level=LogLevel.DEBUG)
async def mypy_determine_partitions(
    request: MyPyRequest, mypy: MyPy, python_setup: PythonSetup
) -> MyPyPartitions:

    resolve_and_interpreter_constraints_to_coarsened_targets = (
        await partition._by_interpreter_constraints_and_resolve(request.field_sets, python_setup)
    )

    return MyPyPartitions(
        MyPyPartition(
            FrozenOrderedSet(roots),
            FrozenOrderedSet(CoarsenedTargets(root_cts).closure()),
            resolve if len(python_setup.resolves) > 1 else None,
            interpreter_constraints or mypy.interpreter_constraints,
        )
        for (resolve, interpreter_constraints), (roots, root_cts) in sorted(
            resolve_and_interpreter_constraints_to_coarsened_targets.items()
        )
    )


# TODO(#10864): Improve performance, e.g. by leveraging the MyPy cache.
@rule(desc="Typecheck using MyPy", level=LogLevel.DEBUG)
async def mypy_typecheck(request: MyPyRequest, mypy: MyPy) -> CheckResults:
    if mypy.skip:
        return CheckResults([], checker_name=request.name)

    partitions = await Get(MyPyPartitions, MyPyRequest, request)
    partitioned_results = await MultiGet(
        Get(CheckResult, MyPyPartition, partition) for partition in partitions
    )
    return CheckResults(partitioned_results, checker_name=request.name)


def rules():
    return [
        *collect_rules(),
        UnionRule(CheckRequest, MyPyRequest),
        *pex_from_targets.rules(),
    ]
