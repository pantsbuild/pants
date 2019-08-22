# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Set

from pants.engine.console import Console
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.goal import Goal, LineOriented
from pants.engine.rules import console_rule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.source.source_root import SourceRoot, SourceRootConfig, SourceRootsCollection


class Roots(LineOriented, Goal):
  """List the repo's registered source roots."""
  name = 'roots'


@rule(SourceRootsCollection, [SourceRootConfig])
def all_roots(source_root_config):

  source_roots = source_root_config.get_source_roots()

  all_paths: Set[str] = set()
  for path in source_roots.traverse():
    if path.startswith("^/"):
      all_paths |= {f"{path[2:]}/"}
    else:
      all_paths |= {f"**/{path}/"}

  snapshot = yield Get(Snapshot, PathGlobs(include=tuple(all_paths)))

  all_source_roots: Set[SourceRoot] = set()
  for directory in sorted(snapshot.dirs):
    match: SourceRoot = source_roots.trie_find(directory)
    if match:
      all_source_roots.add(match)
  yield all_source_roots


@console_rule(Roots, [Console, Roots.Options, SourceRootConfig])
def list_roots(console, options, source_root_config):
  all_roots = yield Get(SourceRootsCollection, SourceRootConfig, source_root_config)

  with Roots.line_oriented(options, console) as (print_stdout, print_stderr):
    for src_root in sorted(all_roots, key=lambda x: x.path):
      all_langs = ','.join(sorted(src_root.langs))
      print_stdout(f"{src_root.path}: {all_langs or '*'}")
  yield Roots(exit_code=0)


def rules():
  return [
      optionable_rule(SourceRootConfig),
      all_roots,
      list_roots,
    ]
