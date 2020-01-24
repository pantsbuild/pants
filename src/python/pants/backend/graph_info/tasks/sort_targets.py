# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.build_graph.build_graph import sort_targets
from pants.task.console_task import ConsoleTask


class SortTargets(ConsoleTask):
  """Topologically sort the targets."""

  _register_console_transitivity_option = False

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--reverse', type=bool,
             help='Sort least-dependent to most-dependent.')
    register(
      '--transitive', type=bool, default=True, fingerprint=True,
      help='If True, use all targets in the build graph, else use only target roots.',
      removal_version="1.27.0.dev0",
      removal_hint="This option has no impact on the goal `sort`.",
    )

  def console_output(self, targets):
    sorted_targets = sort_targets(targets)
    # sort_targets already returns targets in reverse topologically sorted order.
    if not self.get_options().reverse:
      sorted_targets = reversed(sorted_targets)
    for target in sorted_targets:
      if target in self.context.target_roots:
        yield target.address.reference()
