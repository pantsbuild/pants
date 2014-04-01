# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict

from twitter.common.collections import OrderedSet

import pants.base.build_file_context
from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.base.target import Target
from pants.targets.sources import SourceRoot
from pants.tasks import TaskError
from pants.tasks.console_task import ConsoleTask


class ReverseDepmap(ConsoleTask):
  """Outputs all targets whose dependencies include at least one of the input targets."""

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ReverseDepmap, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("transitive"), mkflag("transitive", negate=True),
                            dest="reverse_depmap_transitive", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] List transitive dependees.")

    option_group.add_option(mkflag("closed"), mkflag("closed", negate=True),
                            dest="reverse_depmap_closed", default=False,
                            action="callback", callback=mkflag.set_bool,
                            help="[%default] Include the input targets in the output along with "
                                 "the dependees.")

    option_group.add_option(mkflag('type'), dest='dependees_type', action='append', default=[],
                            help="Identifies target types to include. Multiple type inclusions "
                                 "can be specified at once in a comma separated list or else by "
                                 "using multiple instances of this flag.")

  def __init__(self, context):
    ConsoleTask.__init__(self, context)

    self._transitive = context.options.reverse_depmap_transitive
    self._closed = context.options.reverse_depmap_closed
    self._dependees_type = context.options.dependees_type

  def console_output(self, _):
    buildfiles = OrderedSet()
    if self._dependees_type:
      base_paths = OrderedSet()
      for dependees_type in self._dependees_type:
        try:
          # Try to do a fully qualified import 1st for filtering on custom types.
          from_list, module, type_name = dependees_type.rsplit('.', 2)
          __import__('%s.%s' % (from_list, module), fromlist=[from_list])
        except (ImportError, ValueError):
          # Fall back on pants provided target types.
          if hasattr(pants.base.build_file_context, dependees_type):
            type_name = getattr(pants.base.build_file_context, dependees_type)
          else:
            raise TaskError('Invalid type name: %s' % dependees_type)
        # Find the SourceRoot for the given input type
        base_paths.update(SourceRoot.roots(type_name))
      if not base_paths:
        raise TaskError('No SourceRoot set for any target type in %s.' % self._dependees_type +
                        '\nPlease define a source root in BUILD file as:' +
                        '\n\tsource_root(\'<src-folder>\', %s)' % ', '.join(self._dependees_type))
      for base_path in base_paths:
        buildfiles.update(BuildFile.scan_buildfiles(get_buildroot(), base_path))
    else:
      buildfiles = BuildFile.scan_buildfiles(get_buildroot())

    dependees_by_target = defaultdict(set)
    for buildfile in buildfiles:
      for address in Target.get_all_addresses(buildfile):
        for target in Target.get(address).resolve():
          # TODO(John Sirois): tighten up the notion of targets written down in a BUILD by a
          # user vs. targets created by pants at runtime.
          target = self.get_concrete_target(target)
          if hasattr(target, 'dependencies'):
            for dependencies in target.dependencies:
              for dependency in dependencies.resolve():
                dependency = self.get_concrete_target(dependency)
                dependees_by_target[dependency].add(target)

    roots = set(self.context.target_roots)
    if self._closed:
      for root in roots:
        yield str(root.address)

    for dependant in self.get_dependants(dependees_by_target, roots):
      yield str(dependant.address)

  def get_dependants(self, dependees_by_target, roots):
    check = set(roots)
    known_dependants = set()
    while True:
      dependants = set(known_dependants)
      for target in check:
        dependants.update(dependees_by_target[target])
      check = dependants - known_dependants
      if not check or not self._transitive:
        return dependants - set(roots)
      known_dependants = dependants

  def get_concrete_target(self, target):
    return target.derived_from if isinstance(target, Target) else target
