# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.build_graph.files import Files
from pants.engine.fs import EMPTY_SNAPSHOT, Digest, DirectoryWithPrefixToStrip, Snapshot
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get
from pants.source.source_root import SourceRootConfig


@dataclass(frozen=True)
class SourceRootStrippedSources:
  """Wrapper for a snapshot of targets whose source roots have been stripped."""
  snapshot: Snapshot


@rule
def strip_source_root(
  hydrated_target: HydratedTarget, source_root_config: SourceRootConfig
) -> SourceRootStrippedSources:
  """Relativize targets to their source root, e.g.
  `src/python/pants/util/strutil.py` -> `pants/util/strutil.py ."""

  target_adaptor = hydrated_target.adaptor
  source_roots = source_root_config.get_source_roots()

  # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of raising to
  # simplify the hasattr() checks here!
  if not hasattr(target_adaptor, 'sources'):
    yield SourceRootStrippedSources(snapshot=EMPTY_SNAPSHOT)

  digest = target_adaptor.sources.snapshot.directory_digest
  source_root = source_roots.find_by_path(target_adaptor.address.spec_path)

  # Loose `Files`, as opposed to `Resources` or `Target`s, have no (implied) package
  # structure and so we do not remove their source root like we normally do, so that filesystem
  # APIs may still access the files. See pex_build_util.py's `_create_source_dumper`.
  if target_adaptor.type_alias == Files.alias():
    source_root = None

  resulting_digest = yield Get(
    Digest,
    DirectoryWithPrefixToStrip(
      directory_digest=digest,
      prefix=source_root.path if source_root else ""
    )
  )
  resulting_snapshot = yield Get(Snapshot, Digest, resulting_digest)
  yield SourceRootStrippedSources(snapshot=resulting_snapshot)


def rules():
  return [strip_source_root, optionable_rule(SourceRootConfig)]
