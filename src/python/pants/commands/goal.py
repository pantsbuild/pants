# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import inspect
import os
import sys
import traceback

from twitter.common import log
from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir
from twitter.common.lang import Compatibility
from twitter.common.log.options import LogOptions

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.core.tasks.task import Task
from pants.base.address import BuildFileAddress, parse_spec
from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.base.config import Config, ConfigOption
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.base.rcfile import RcFile
from pants.base.spec_parser import SpecParser
from pants.base.target import Target
from pants.base.workunit import WorkUnit
from pants.commands.command import Command
from pants.engine.engine import Engine
from pants.engine.linear_engine import LinearEngine
from pants.goal import Context, GoalError, Phase
from pants.goal.help import print_help
from pants.goal.initialize_reporting import update_reporting
from pants.goal.option_helpers import add_global_options
from pants.backend.jvm.tasks.nailgun_task import NailgunTask  # XXX(pl)


StringIO = Compatibility.StringIO


class Goal(Command):
  """Lists installed goals or else executes a named goal."""

  __command__ = 'goal'
  output = None

  @staticmethod
  def parse_args(args):
    goals = OrderedSet()
    specs = OrderedSet()
    explicit_multi = False

    def is_spec(spec):
      return os.sep in spec or ':' in spec

    for i, arg in enumerate(args):
      if not arg.startswith('-'):
        specs.add(arg) if is_spec(arg) else goals.add(arg)
      elif '--' == arg:
        if specs:
          raise GoalError('Cannot intermix targets with goals when using --. Targets should '
                          'appear on the right')
        explicit_multi = True
        del args[i]
        break

    if explicit_multi:
      specs.update(arg for arg in args[len(goals):] if not arg.startswith('-'))

    return goals, specs

  # TODO(John Sirois): revisit wholesale locking when we move py support into pants new
  @classmethod
  def serialized(cls):
    # Goal serialization is now handled in goal execution during group processing.
    # The goal command doesn't need to hold the serialization lock; individual goals will
    # acquire the lock if they need to be serialized.
    return False

  def __init__(self, *args, **kwargs):
    self.targets = []
    self.config = None
    super(Goal, self).__init__(*args, **kwargs)

  @contextmanager
  def check_errors(self, banner):
    errors = {}
    def error(key, include_traceback=False):
      exc_type, exc_value, _ = sys.exc_info()
      msg = StringIO()
      if include_traceback:
        frame = inspect.trace()[-2]
        filename = frame[1]
        lineno = frame[2]
        funcname = frame[3]
        code = ''.join(frame[4]) if frame[4] else None
        traceback.print_list([(filename, lineno, funcname, code)], file=msg)
      if exc_type:
        msg.write(''.join(traceback.format_exception_only(exc_type, exc_value)))
      errors[key] = msg.getvalue()
      sys.exc_clear()

    yield error

    if errors:
      msg = StringIO()
      msg.write(banner)
      invalid_keys = [key for key, exc in errors.items() if not exc]
      if invalid_keys:
        msg.write('\n  %s' % '\n  '.join(invalid_keys))
      for key, exc in errors.items():
        if exc:
          msg.write('\n  %s =>\n    %s' % (key, '\n      '.join(exc.splitlines())))
      # The help message for goal is extremely verbose, and will obscure the
      # actual error message, so we don't show it in this case.
      self.error(msg.getvalue(), show_help=False)

  def setup_parser(self, parser, args):
    self.config = Config.load()
    add_global_options(parser)

    # We support attempting zero or more goals.  Multiple goals must be delimited from further
    # options and non goal args with a '--'.  The key permutations we need to support:
    # ./pants goal => goals
    # ./pants goal goals => goals
    # ./pants goal compile src/java/... => compile
    # ./pants goal compile -x src/java/... => compile
    # ./pants goal compile src/java/... -x => compile
    # ./pants goal compile run -- src/java/... => compile, run
    # ./pants goal compile run -- src/java/... -x => compile, run
    # ./pants goal compile run -- -x src/java/... => compile, run

    if not args:
      args.append('help')

    help_flags = set(['-h', '--help', 'help'])
    show_help = len(help_flags.intersection(args)) > 0
    non_help_args = filter(lambda f: f not in help_flags, args)

    goals, specs = Goal.parse_args(non_help_args)
    if show_help:
      print_help(goals)
      sys.exit(0)

    self.requested_goals = goals

    with self.run_tracker.new_workunit(name='setup', labels=[WorkUnit.SETUP]):
      # Bootstrap user goals by loading any BUILD files implied by targets.
      spec_parser = SpecParser(self.root_dir, self.build_file_parser)
      with self.run_tracker.new_workunit(name='parse', labels=[WorkUnit.SETUP]):
        for spec in specs:
          for address in spec_parser.parse_addresses(spec):
            self.build_file_parser.inject_spec_closure_into_build_graph(address.spec,
                                                                        self.build_graph)
            self.targets.append(self.build_graph.get_target(address))
    self.phases = [Phase(goal) for goal in goals]

    rcfiles = self.config.getdefault('rcfiles', type=list,
                                     default=['/etc/pantsrc', '~/.pants.rc'])
    if rcfiles:
      rcfile = RcFile(rcfiles, default_prepend=False, process_default=True)

      # Break down the goals specified on the command line to the full set that will be run so we
      # can apply default flags to inner goal nodes.  Also break down goals by Task subclass and
      # register the task class hierarchy fully qualified names so we can apply defaults to
      # baseclasses.

      sections = OrderedSet()
      for phase in Engine.execution_order(self.phases):
        for goal in phase.goals():
          sections.add(goal.name)
          for clazz in goal.task_type.mro():
            if clazz == Task:
              break
            sections.add('%s.%s' % (clazz.__module__, clazz.__name__))

      augmented_args = rcfile.apply_defaults(sections, args)
      if augmented_args != args:
        # TODO(John Sirois): Cleanup this currently important mutation of the passed in args
        # once the 2-layer of command -> goal is squashed into one.
        del args[:]
        args.extend(augmented_args)
        sys.stderr.write("(using pantsrc expansion: pants goal %s)\n" % ' '.join(augmented_args))

    Phase.setup_parser(parser, args, self.phases)

  def run(self, lock):
    # TODO(John Sirois): Consider moving to straight python logging.  The divide between the
    # context/work-unit logging and standard python logging doesn't buy us anything.

    # Enable standard python logging for code with no handle to a context/work-unit.
    if self.options.log_level:
      LogOptions.set_stderr_log_level((self.options.log_level or 'info').upper())
      logdir = self.options.logdir or self.config.get('goals', 'logdir', default=None)
      if logdir:
        safe_mkdir(logdir)
        LogOptions.set_log_dir(logdir)
        log.init('goals')
      else:
        log.init()

    # Update the reporting settings, now that we have flags etc.
    def is_console_task():
      for phase in self.phases:
        for goal in phase.goals():
          if issubclass(goal.task_type, ConsoleTask):
            return True
      return False

    is_explain = self.options.explain
    update_reporting(self.options, is_console_task() or is_explain, self.run_tracker)

    context = Context(
      self.config,
      self.options,
      self.run_tracker,
      self.targets,
      requested_goals=self.requested_goals,
      build_graph=self.build_graph,
      build_file_parser=self.build_file_parser,
      lock=lock)

    unknown = []
    for phase in self.phases:
      if not phase.goals():
        unknown.append(phase)

    if unknown:
      context.log.error('Unknown goal(s): %s\n' % ' '.join(phase.name for phase in unknown))
      return 1

    engine = LinearEngine()
    return engine.execute(context, self.phases)

  def cleanup(self):
    # TODO: This is JVM-specific and really doesn't belong here.
    # TODO: Make this more selective? Only kill nailguns that affect state? E.g., checkstyle
    # may not need to be killed.
    NailgunTask.killall(log.info)
    sys.exit(1)
