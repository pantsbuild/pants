# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.pex import Pex, PexRequest, PexRequirements
from pants.backend.python.rules.pex_from_targets import (
    PexFromTargetsRequest,
    requirements_pex_from_targets_request,
)
from pants.backend.python.rules.python_sources import PythonSourceFiles, PythonSourceFilesRequest
from pants.backend.python.subsystems.ipython import IPython
from pants.core.goals.repl import ReplImplementation, ReplRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule


class PythonRepl(ReplImplementation):
    name = "python"


@rule
async def create_python_repl_request(repl: PythonRepl) -> ReplRequest:
    requirements_request = Get(
        Pex,
        PexFromTargetsRequest,
        requirements_pex_from_targets_request(Addresses(tgt.address for tgt in repl.targets)),
    )
    sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(repl.targets, include_files=True)
    )
    requirements_pex, sources = await MultiGet(requirements_request, sources_request)
    merged_digest = await Get(
        Digest, MergeDigests((requirements_pex.digest, sources.source_files.snapshot.digest))
    )
    return ReplRequest(
        digest=merged_digest,
        binary_name=requirements_pex.output_filename,
        env={"PEX_EXTRA_SYS_PATH": ":".join(sources.source_roots)},
    )


class IPythonRepl(ReplImplementation):
    name = "ipython"


@rule
async def create_ipython_repl_request(repl: IPythonRepl, ipython: IPython) -> ReplRequest:
    # Note that unlike above, we get an intermediate PexRequest here (instead of going straight
    # to a Pex) so that we can capture the interpreter constraints.
    requirements_pex_request = await Get(
        PexRequest,
        PexFromTargetsRequest,
        requirements_pex_from_targets_request(Addresses(tgt.address for tgt in repl.targets)),
    )

    sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(repl.targets, include_files=True)
    )

    ipython_request = Get(
        Pex,
        PexRequest(
            output_filename="ipython.pex",
            entry_point=ipython.entry_point,
            requirements=PexRequirements(ipython.all_requirements),
            interpreter_constraints=requirements_pex_request.interpreter_constraints,
            additional_args=("--pex-path", requirements_pex_request.output_filename,),
        ),
    )

    requirements_pex, sources, ipython_pex = await MultiGet(
        Get(Pex, PexRequest, requirements_pex_request), sources_request, ipython_request
    )
    merged_digest = await Get(
        Digest,
        MergeDigests(
            (requirements_pex.digest, sources.source_files.snapshot.digest, ipython_pex.digest)
        ),
    )
    return ReplRequest(
        digest=merged_digest,
        binary_name=ipython_pex.output_filename,
        env={"PEX_EXTRA_SYS_PATH": ":".join(sources.source_roots)},
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(ReplImplementation, PythonRepl),
        UnionRule(ReplImplementation, IPythonRepl),
    ]
