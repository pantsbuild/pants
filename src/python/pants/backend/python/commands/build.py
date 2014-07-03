# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import sys
import traceback

from twitter.common.collections import OrderedSet

from pants.base.config import Config
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.commands.command import Command
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.python_builder import PythonBuilder


class Build(Command):
  """Builds a specified target."""

  __command__ = 'build'

  def setup_parser(self, parser, args):
    parser.set_usage("\n"
                     "  %prog build (options) [spec] (build args)\n"
                     "  %prog build (options) [spec]... -- (build args)")
    parser.add_option("-t", "--timeout", dest="conn_timeout", type="int",
                      default=Config.load().getdefault('connection_timeout'),
                      help="Number of seconds to wait for http connections.")
    parser.add_option('-i', '--interpreter', dest='interpreters', default=[], action='append',
                      help="Constrain what Python interpreters to use.  Uses Requirement "
                           "format from pkg_resources, e.g. 'CPython>=2.6,<3' or 'PyPy'. "
                           "By default, no constraints are used.  Multiple constraints may "
                           "be added.  They will be ORed together.")
    parser.add_option('-v', '--verbose', dest='verbose', default=False, action='store_true',
                      help='Show verbose output.')
    parser.add_option('-f', '--fast', dest='fast', default=False, action='store_true',
                      help='Run tests in a single chroot.')
    parser.disable_interspersed_args()
    parser.epilog = ('Builds the specified Python target(s). Use ./pants goal for JVM and other '
                     'targets.')

  def __init__(self, *args, **kwargs):
    super(Build, self).__init__(*args, **kwargs)

    if not self.args:
      self.error("A spec argument is required")

    self.config = Config.load()

    interpreters = self.options.interpreters or [b'']
    self.interpreter_cache = PythonInterpreterCache(self.config, logger=self.debug)
    self.interpreter_cache.setup(filters=interpreters)
    interpreters = self.interpreter_cache.select_interpreter(
        list(self.interpreter_cache.matches(interpreters)))
    if len(interpreters) != 1:
      self.error('Unable to detect suitable interpreter.')
    else:
      self.debug('Selected %s' % interpreters[0])
    self.interpreter = interpreters[0]

    try:
      specs_end = self.args.index('--')
      if len(self.args) > specs_end:
        self.build_args = self.args[specs_end+1:len(self.args)+1]
      else:
        self.build_args = []
    except ValueError:
      specs_end = 1
      self.build_args = self.args[1:] if len(self.args) > 1 else []

    self.targets = OrderedSet()
    spec_parser = CmdLineSpecParser(self.root_dir, self.build_file_parser)
    self.top_level_addresses = set()

    specs = self.args[0:specs_end]
    addresses = spec_parser.parse_addresses(specs)

    for address in addresses:
      self.top_level_addresses.add(address)
      try:
        self.build_file_parser.inject_address_closure_into_build_graph(address, self.build_graph)
        target = self.build_graph.get_target(address)
      except:
        self.error("Problem parsing BUILD target %s: %s" % (address, traceback.format_exc()))

      if not target:
        self.error("Target %s does not exist" % address)

      transitive_targets = self.build_graph.transitive_subgraph_of_addresses([target.address])
      for transitive_target in transitive_targets:
        self.targets.add(transitive_target)

    self.targets = [target for target in self.targets if target.is_python]

  def debug(self, message):
    if self.options.verbose:
      print(message, file=sys.stderr)

  def execute(self):
    print("Build operating on top level addresses: %s" % self.top_level_addresses)

    python_targets = OrderedSet()
    for target in self.targets:
      if target.is_python:
        python_targets.add(target)
      else:
        self.error("Cannot build target %s" % target)

    if python_targets:
      status = self._python_build(python_targets)
    else:
      status = -1

    return status

  def _python_build(self, targets):
    try:
      executor = PythonBuilder(self.run_tracker)
      return executor.build(
        targets,
        self.build_args,
        interpreter=self.interpreter,
        conn_timeout=self.options.conn_timeout,
        fast_tests=self.options.fast)
    except:
      self.error("Problem executing PythonBuilder for targets %s: %s" % (targets,
                                                                         traceback.format_exc()))
