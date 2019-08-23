# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Set

from pants.engine.console import Console
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.goal import Goal, LineOriented
from pants.engine.rules import console_rule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.source.source_root import AllSourceRoots, SourceRoot, SourceRootConfig


class Roots(LineOriented, Goal):
  """List the repo's registered source roots."""
  name = 'roots'


@rule(AllSourceRoots, [SourceRootConfig])
def all_roots(source_root_config):

  source_roots = source_root_config.get_source_roots()

  all_paths: Set[str] = set()
  for path in source_roots.traverse():
    if path.startswith("^/"):
      all_paths.add(f"{path[2:]}/")
    else:
      all_paths.add(f"**/{path}/")

  snapshot = yield Get(Snapshot, PathGlobs(include=tuple(all_paths)))

  all_source_roots: Set[SourceRoot] = set()

  # The globs above can match on subdirectories of the source roots.
  # For instance, `src/*/` might match 'src/rust/' as well as
  # 'src/rust/engine/process_execution/bazel_protos/src/gen'.
  # So we use find_by_path to verify every candidate source root.
  for directory in snapshot.dirs:
    match: SourceRoot = source_roots.find_by_path(directory)
    if match:
      all_source_roots.add(match)

  yield AllSourceRoots(all_source_roots)


@console_rule(Roots, [Console, Roots.Options, AllSourceRoots])
def list_roots(console, options, all_roots):
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
