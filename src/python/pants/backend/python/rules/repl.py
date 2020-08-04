# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.pex import Pex
from pants.backend.python.rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.rules.python_sources import PythonSourceFiles, PythonSourceFilesRequest
from pants.backend.python.subsystems.ipython import IPython
from pants.backend.python.target_types import PythonSources
from pants.core.goals.repl import ReplImplementation, ReplRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule


class PythonRepl(ReplImplementation):
    name = "python"
    required_fields = (PythonSources,)


@rule
async def create_python_repl_request(repl: PythonRepl) -> ReplRequest:
    pex_request = Get(
        Pex,
        PexFromTargetsRequest(
            (tgt.address for tgt in repl.targets),
            output_filename="python.pex",
            include_source_files=False,
        ),
    )
    sources_request = Get(PythonSourceFiles, PythonSourceFilesRequest(repl.targets))
    pex, sources = await MultiGet(pex_request, sources_request)
    merged_digest = await Get(
        Digest, MergeDigests((pex.digest, sources.source_files.snapshot.digest))
    )
    return ReplRequest(
        digest=merged_digest,
        binary_name=pex.output_filename,
        env={"PEX_EXTRA_SYS_PATH": ":".join(sources.source_roots)},
    )


class IPythonRepl(ReplImplementation):
    name = "ipython"
    required_fields = (PythonSources,)


@rule
async def create_ipython_repl_request(repl: IPythonRepl, ipython: IPython) -> ReplRequest:
    pex_request = Get(
        Pex,
        PexFromTargetsRequest(
            (tgt.address for tgt in repl.targets),
            output_filename="ipython.pex",
            entry_point=ipython.entry_point,
            additional_requirements=ipython.all_requirements,
            include_source_files=True,
        ),
    )
    sources_request = Get(PythonSourceFiles, PythonSourceFilesRequest(repl.targets))
    pex, sources = await MultiGet(pex_request, sources_request)
    merged_digest = await Get(
        Digest, MergeDigests((pex.digest, sources.source_files.snapshot.digest))
    )
    return ReplRequest(
        digest=merged_digest,
        binary_name=pex.output_filename,
        env={"PEX_EXTRA_SYS_PATH": ":".join(sources.source_roots)},
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(ReplImplementation, PythonRepl),
        UnionRule(ReplImplementation, IPythonRepl),
    ]
