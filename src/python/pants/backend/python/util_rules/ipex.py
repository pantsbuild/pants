# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import json
import shlex
from dataclasses import dataclass

from pants.backend.python.target_types import EntryPoint, Executable, PexLayout
from pants.backend.python.util_rules.ipex_launcher import APP_CODE_PREFIX
from pants.backend.python.util_rules.pex import PexRequest, create_pex
from pants.backend.python.util_rules.pex_cli import PexCli
from pants.backend.python.util_rules.pex_requirements import (
    EntireLockfile,
    PexRequirements,
    Resolve,
    ResolveConfigRequest,
    determine_resolve_config,
)
from pants.core.util_rules import system_binaries
from pants.core.util_rules.stripped_source_files import StrippedFileNameRequest, strip_file_name
from pants.core.util_rules.system_binaries import UnzipBinary
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, CreateDigest, FileContent, MergeDigests
from pants.engine.intrinsics import add_prefix, create_digest, digest_to_snapshot, merge_digests
from pants.engine.process import Process, fallible_to_exec_result_or_raise
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.util.frozendict import FrozenDict
from pants.util.resources import read_sibling_resource


@dataclass(frozen=True)
class IpexRequest:
    underlying_request: PexRequest


def _resolve_name(requirements: PexRequirements | EntireLockfile) -> str | None:
    if isinstance(requirements, EntireLockfile):
        return requirements.lockfile.resolve_name
    if isinstance(requirements.from_superset, Resolve):
        return requirements.from_superset.name
    return None


async def _pex_args_for_hydrated_pex(request: PexRequest) -> tuple[str, ...]:
    args = []
    if request.main is not None:
        if isinstance(request.main, Executable):
            stripped = await strip_file_name(StrippedFileNameRequest(request.main.spec))
            args.extend(("--executable", stripped.value))
        else:
            args.extend(request.main.iter_pex_args())
    args.extend(
        f"--inject-args={shlex.quote(injected_arg)}" for injected_arg in request.inject_args
    )
    args.extend(f"--inject-env={key}={value}" for key, value in sorted(request.inject_env.items()))
    return tuple(args)


@rule
async def create_ipex(request: IpexRequest, unzip: UnzipBinary) -> PexRequest:
    # 1. Create the original PEX as-is without sources, in order to get the
    #    transitively-resolved requirements from its PEX-INFO.
    original_request = request.underlying_request

    # Removing the entry point and sources means this process execution can stay cached even when
    # the source files change. That matters for large resolves, which can take minutes uncached.
    requirements_only_request = dataclasses.replace(
        original_request,
        layout=PexLayout.ZIPAPP,
        main=None,
        sources=None,
        additional_inputs=EMPTY_DIGEST,
        inject_args=(),
        inject_env=FrozenDict(),
        additional_args=(),
        pex_path=(),
        description=f"Resolving requirements for {original_request.output_filename}",
    )
    requirements_only_pex = await create_pex(**implicitly(requirements_only_request))

    # 2. Extract its PEX-INFO. The hydrated PEX generated at runtime will use this data to preserve
    #    the original resolved requirements.
    pex_info_result = await fallible_to_exec_result_or_raise(
        **implicitly(
            Process(
                argv=(unzip.path, "-p", requirements_only_pex.name, "PEX-INFO"),
                input_digest=requirements_only_pex.digest,
                description=f"Extract PEX-INFO from {requirements_only_pex.name}",
            )
        )
    )

    # 3. Add the original source files in a subdirectory and compute the PEX args needed to recreate
    #    the original entry point and injected args/env.
    resolve_config, prefixed_sources_digest, pex_args = await concurrently(
        determine_resolve_config(
            ResolveConfigRequest(_resolve_name(original_request.requirements)), **implicitly()
        ),
        add_prefix(AddPrefix(original_request.sources or EMPTY_DIGEST, APP_CODE_PREFIX)),
        _pex_args_for_hydrated_pex(original_request),
    )
    prefixed_sources = await digest_to_snapshot(prefixed_sources_digest)

    # 4. Create IPEX-INFO, BOOTSTRAP-PEX-INFO, and the launcher.
    #
    # IPEX-INFO is interpreted by ipex_launcher.py:
    # {
    #   "code": [<source files to add to the hydrated PEX when bootstrapped>],
    #   "resolver_settings": {<indexes and find-links to use when bootstrapping>},
    #   "pex_args": [<entry point and injected args/env to apply to the hydrated PEX>],
    # }
    ipex_info = {
        "code": sorted(prefixed_sources.files),
        "resolver_settings": {
            "indexes": list(resolve_config.indexes),
            "find_links": list(resolve_config.find_links),
        },
        "pex_args": list(pex_args),
    }

    pex_version = PexCli.default_version.removeprefix("v")
    # BOOTSTRAP-PEX-INFO is the original requirements-only PEX-INFO. The hydrated PEX generated
    # when the ipex first runs uses it to recover the resolved requirement set.
    #
    # ipex_launcher.py is the bootstrap script that hydrates the ipex with fully resolved
    # requirements before executing the hydrated PEX.
    metadata_digest, launcher_digest = await concurrently(
        create_digest(
            CreateDigest(
                [
                    FileContent("BOOTSTRAP-PEX-INFO", pex_info_result.stdout),
                    FileContent("IPEX-INFO", json.dumps(ipex_info).encode()),
                ]
            )
        ),
        create_digest(
            CreateDigest(
                [
                    FileContent(
                        "pants/backend/python/util_rules/ipex_launcher.py",
                        read_sibling_resource(__name__, "ipex_launcher.py"),
                    )
                ]
            )
        ),
    )

    # 5. Merge all injected files, along with the prefixed source files, into the final ipex input.
    ipex_sources = await merge_digests(
        MergeDigests((prefixed_sources.digest, metadata_digest, launcher_digest))
    )

    # The final ipex should not contain the original requirements, or its bootstrap PEX would try to
    # import distributions that are intentionally absent. Instead, it contains only PEX and the
    # launcher; the hydrated PEX created on first execution resolves the original requirements from
    # BOOTSTRAP-PEX-INFO.
    return dataclasses.replace(
        original_request,
        layout=PexLayout.ZIPAPP,
        requirements=PexRequirements((f"pex=={pex_version}",)),
        main=EntryPoint("pants.backend.python.util_rules.ipex_launcher", "main"),
        sources=ipex_sources,
        additional_inputs=EMPTY_DIGEST,
        inject_args=(),
        inject_env=FrozenDict(),
        additional_args=(),
        pex_path=(),
        description=f"Building dehydrated ipex {original_request.output_filename}",
    )


def rules():
    return (
        *collect_rules(),
        *system_binaries.rules(),
    )
