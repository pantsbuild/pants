# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass
from io import BytesIO
from typing import Iterable

from pants.backend.python.subsystems.setuptools import PythonDistributionFieldSet
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexRequest, PexRequirements
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.python_sources import PythonSourceFiles
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.util_rules.source_files import SourceFiles
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, DigestContents, DigestSubset, MergeDigests, PathGlobs, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.util.dirutil import fast_relpath_optional
from pants.util.docutil import doc_url
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@frozen_after_init
@dataclass(unsafe_hash=True)
class LocalDistsPexRequest:
    """Request to build the local dists from the dependency closure of a set of addresses."""

    addresses: Addresses
    internal_only: bool
    interpreter_constraints: InterpreterConstraints
    # The result will return these with the sources provided by the dists subtracted out.
    # This will help the caller prevent sources from appearing twice on sys.path.
    sources: PythonSourceFiles

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        internal_only: bool,
        interpreter_constraints: InterpreterConstraints = InterpreterConstraints(),
        sources: PythonSourceFiles = PythonSourceFiles.empty(),
    ) -> None:
        self.addresses = Addresses(addresses)
        self.internal_only = internal_only
        self.interpreter_constraints = interpreter_constraints
        self.sources = sources


@dataclass(frozen=True)
class LocalDistsPex:
    """A PEX file containing locally-built dists.

    Can be consumed from another PEX, e.g., by adding to PEX_PATH.

    The PEX will only contain locally built dists and not their dependencies. For Pants generated
    `setup.py` / `pyproject.toml`, the dependencies will be included in the standard resolve process
    that the locally-built dists PEX is adjoined to via PEX_PATH. For hand-made `setup.py` /
    `pyproject.toml` with 3rdparty dependencies not hand-mirrored into BUILD file dependencies, this
    will lead to issues. See https://github.com/pantsbuild/pants/issues/13587#issuecomment-974863636
    for one way to fix this corner which is intentionally punted on for now.

    Lists the files provided by the dists on sys.path, so they can be subtracted from
    sources digests, to prevent the same file ending up on sys.path twice.
    """

    pex: Pex
    # The sources from the request, but with any files provided by the local dists subtracted out.
    remaining_sources: PythonSourceFiles


@rule(desc="Building local distributions")
async def build_local_dists(
    request: LocalDistsPexRequest,
) -> LocalDistsPex:

    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses))
    applicable_targets = [
        tgt for tgt in transitive_targets.closure if PythonDistributionFieldSet.is_applicable(tgt)
    ]

    python_dist_field_sets = [
        PythonDistributionFieldSet.create(target) for target in applicable_targets
    ]

    dists = await MultiGet(
        [Get(BuiltPackage, PackageFieldSet, field_set) for field_set in python_dist_field_sets]
    )

    # The primary use-case of the "local dists" feature is to support consuming native extensions
    # as wheels without having to publish them first.
    # It doesn't seem very useful to consume locally-built sdists, and it makes it hard to
    # reason about possible sys.path collisions between the in-repo sources and whatever the
    # sdist will place on the sys.path when it's installed.
    # So for now we simply ignore sdists, with a warning if necessary.
    provided_files = set()
    wheels = []

    all_contents = await MultiGet(Get(DigestContents, Digest, dist.digest) for dist in dists)
    for dist, contents, tgt in zip(dists, all_contents, applicable_targets):
        artifacts = {(a.relpath or "") for a in dist.artifacts}
        # A given local dist might build a wheel and an sdist (and maybe other artifacts -
        # we don't know what setup command was run...)
        # As long as there is a wheel, we can ignore the other artifacts.
        wheel = next((art for art in artifacts if art.endswith(".whl")), None)
        if wheel:
            wheel_content = next(content for content in contents if content.path == wheel)
            wheels.append(wheel)
            buf = BytesIO()
            buf.write(wheel_content.content)
            buf.seek(0)
            with zipfile.ZipFile(buf) as zf:
                provided_files.update(zf.namelist())
        else:
            logger.warning(
                f"Encountered a dependency on the {tgt.alias} target at {tgt.address.spec}, but "
                "this target does not produce a Python wheel artifact. Therefore this target's "
                "code will be used directly from sources, without a distribution being built, "
                "and therefore any native extensions in it will not be built.\n\n"
                f"See {doc_url('python-distributions')} for details on how to set up a {tgt.alias} "
                "target to produce a wheel."
            )

    dists_digest = await Get(Digest, MergeDigests([dist.digest for dist in dists]))
    wheels_digest = await Get(Digest, DigestSubset(dists_digest, PathGlobs(["**/*.whl"])))

    dists_pex = await Get(
        Pex,
        PexRequest(
            output_filename="local_dists.pex",
            requirements=PexRequirements(wheels),
            interpreter_constraints=request.interpreter_constraints,
            additional_inputs=wheels_digest,
            internal_only=request.internal_only,
            additional_args=["--intransitive"],
        ),
    )

    # We check source roots in reverse lexicographic order,
    # so we'll find the innermost root that matches.
    source_roots = list(reversed(sorted(request.sources.source_roots)))
    remaining_sources = set(request.sources.source_files.files)
    unrooted_files_set = set(request.sources.source_files.unrooted_files)
    for source in request.sources.source_files.files:
        if source not in unrooted_files_set:
            for source_root in source_roots:
                source_relpath = fast_relpath_optional(source, source_root)
                if source_relpath is not None and source_relpath in provided_files:
                    remaining_sources.remove(source)
    remaining_sources_snapshot = await Get(
        Snapshot,
        DigestSubset(
            request.sources.source_files.snapshot.digest, PathGlobs(sorted(remaining_sources))
        ),
    )
    subtracted_sources = PythonSourceFiles(
        SourceFiles(remaining_sources_snapshot, request.sources.source_files.unrooted_files),
        request.sources.source_roots,
    )

    return LocalDistsPex(dists_pex, subtracted_sources)


def rules():
    return (*collect_rules(), *pex_rules())
