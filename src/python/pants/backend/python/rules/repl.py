# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.pex import Pex
from pants.backend.python.rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.rules.python_sources import (
    UnstrippedPythonSources,
    UnstrippedPythonSourcesRequest,
)
from pants.backend.python.subsystems.ipython import IPython
from pants.backend.python.target_types import PythonSources
from pants.core.goals.repl import ReplImplementation, ReplRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
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
            distributed_to_users=False,
            include_source_files=False,
        ),
    )
    source_files_request = Get(
        UnstrippedPythonSources, UnstrippedPythonSourcesRequest(repl.targets)
    )
    pex, source_files = await MultiGet(pex_request, source_files_request)
    merged_digest = await Get(Digest, MergeDigests((pex.digest, source_files.snapshot.digest)))
    return ReplRequest(
        digest=merged_digest,
        binary_name=pex.output_filename,
        env={"PEX_EXTRA_SYS_PATH": ":".join(source_files.source_roots)},
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
            distributed_to_users=False,
            entry_point=ipython.get_entry_point(),
            additional_requirements=ipython.get_requirement_specs(),
            include_source_files=True,
        ),
    )
    source_files_request = Get(
        UnstrippedPythonSources, UnstrippedPythonSourcesRequest(repl.targets)
    )
    pex, source_files = await MultiGet(pex_request, source_files_request)
    merged_digest = await Get(Digest, MergeDigests((pex.digest, source_files.snapshot.digest)))
    return ReplRequest(
        digest=merged_digest,
        binary_name=pex.output_filename,
        env={"PEX_EXTRA_SYS_PATH": ":".join(source_files.source_roots)},
    )


def rules():
    return [
        SubsystemRule(IPython),
        UnionRule(ReplImplementation, PythonRepl),
        UnionRule(ReplImplementation, IPythonRepl),
        create_python_repl_request,
        create_ipython_repl_request,
    ]
