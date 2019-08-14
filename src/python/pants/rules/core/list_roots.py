# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.console import Console
from pants.engine.goal import Goal, LineOriented
from pants.engine.rules import console_rule, optionable_rule
from pants.source.source_root import SourceRootConfig


class Roots(LineOriented, Goal):
  """List the repo's registered source roots."""
  name = 'roots'


@console_rule(Roots, [Console, Roots.Options, SourceRootConfig])
def list_roots(console, options, source_root_config):
  all_roots = source_root_config.get_source_roots().all_roots()
  with Roots.line_oriented(options, console) as (print_stdout, print_stderr):
    for src_root in all_roots:
      all_langs = ','.join(sorted(src_root.langs))
      print_stdout(f"{src_root.path}: {all_langs or '*'}")
  yield Roots(exit_code=0)


def rules():
  return [
      optionable_rule(SourceRootConfig),
      list_roots,
    ]
