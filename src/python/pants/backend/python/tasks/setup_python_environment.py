# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from functools import reduce

from pants.backend.core.tasks.task import Task
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.targets.python_root import is_python_root
from pants.base.exceptions import TaskError


class SetupPythonEnvironment(Task):
  """
    Establishes the python intepreter(s) for downstream Python tasks e.g. Resolve, Run, PytestRun.

    Populates the product namespace (for typename = 'python'):
      'intepreters': ordered list of PythonInterpreter objects
  """
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("force"), dest="python_setup_force",
                            action="store_true", default=False,
                            help="Force clean and install.")
    option_group.add_option(mkflag("path"), dest="python_setup_paths",
                            action="append", default=[],
                            help="Add a path to search for interpreters, by default PATH.")
    option_group.add_option(mkflag("interpreter"), dest="python_interpreter",
                            default=[], action='append',
                            help="Constrain what Python interpreters to use.  Uses Requirement "
                                 "format from pkg_resources, e.g. 'CPython>=2.6,<3' or 'PyPy'. "
                                 "By default, no constraints are used.  Multiple constraints may "
                                 "be added.  They will be ORed together.")
    option_group.add_option(mkflag("multi"), dest="python_multi",
                            default=False, action='store_true',
                            help="Allow multiple interpreters to be bound to an upstream chroot.")

  def __init__(self, context, workdir):
    context.products.require('python')
    self._cache = PythonInterpreterCache(context.config, logger=context.log.debug)
    super(SetupPythonEnvironment, self).__init__(context, workdir)

  def execute(self):
    ifilters = self.context.options.python_interpreter
    self._cache.setup(force=self.context.options.python_setup_force,
        paths=self.context.options.python_setup_paths,
        filters=ifilters or [b''])
    all_interpreters = set(self._cache.interpreters)
    for target in self.context.targets(is_python_root):
      self.context.log.info('Setting up interpreters for %s' % target)
      closure = target.closure()
      self.context.log.debug('  - Target closure: %d targets' % len(closure))
      target_compatibilities = [
          set(self._cache.matches(getattr(closure_target, 'compatibility', [''])))
          for closure_target in closure]
      target_compatibilities = reduce(set.intersection, target_compatibilities, all_interpreters)
      self.context.log.debug('  - Target minimum compatibility: %s' % (
        ' '.join(interp.version_string for interp in target_compatibilities)))
      interpreters = self._cache.select_interpreter(target_compatibilities,
          allow_multiple=self.context.options.python_multi)
      self.context.log.debug('  - Selected: %s' % interpreters)
      if not interpreters:
        raise TaskError('No compatible interpreters for %s' % target)
      target.interpreters = interpreters
