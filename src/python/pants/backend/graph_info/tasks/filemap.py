# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.task.console_task import ConsoleTask


class Filemap(ConsoleTask):
  """Print a mapping from source file to the target that owns the source file."""

  _register_console_transitivity_option = False

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      '--transitive', type=bool, default=True, fingerprint=True,
      help='If True, use all targets in the build graph, else use only target roots.',
      removal_version="1.27.0.dev0",
      removal_hint="This option has no impact on the goal `filemap`.",
    )

  def console_output(self, _):
    visited = set()
    for target in self.determine_target_roots('filemap'):
      if target not in visited:
        visited.add(target)
        for rel_source in target.sources_relative_to_buildroot():
          yield '{} {}'.format(rel_source, target.address.spec)
