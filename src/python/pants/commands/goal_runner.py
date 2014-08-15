# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import copy
import inspect
import logging
import os
import sys
import traceback

from twitter.common import log
from twitter.common.collections import OrderedSet
from twitter.common.lang import Compatibility
from twitter.common.log.options import LogOptions

from pants.backend.core.tasks.task import QuietTaskMixin, Task
from pants.backend.jvm.tasks.nailgun_task import NailgunTask  # XXX(pl)
from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.base.build_graph import MissingAddressError
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.config import Config
from pants.base.rcfile import RcFile
from pants.base.workunit import WorkUnit
from pants.commands.command import Command
from pants.engine.engine import Engine
from pants.engine.round_engine import RoundEngine
from pants.goal.context import Context
from pants.goal.error import GoalError
from pants.goal.help import print_help
from pants.goal.initialize_reporting import update_reporting
from pants.goal.option_helpers import add_global_options
from pants.goal.goal import Goal
from pants.util.dirutil import safe_mkdir


StringIO = Compatibility.StringIO


class GoalRunner(Command):
  """Lists installed goals or else executes a named goal."""

  class IntermixedArgumentsError(GoalError):
    pass

  __command__ = 'goal'
  output = None

  @staticmethod
  def parse_args(args):
    goals = OrderedSet()
    specs = OrderedSet()
    explicit_multi = False
    logger = logging.getLogger(__name__)
    has_double_dash = u'--' in args
    goal_names = [goal.name for goal in Goal.all()]
    if not goal_names:
      raise GoalError(
        'Arguments cannot be parsed before the list of goals from Goal.all() is populated.')

    def is_spec(spec):
      if os.sep in spec or ':' in spec:
        return True # Definitely not a goal.
      if not (spec in goal_names):
        return True # Definitely not a (known) goal.
      if has_double_dash:
        # This means that we're parsing the half of the expression before a --, so assume it's a
        # goal without warning.
        return False
      # Here, it's possible we have a goal and target with the same name. For now, always give
      # priority to the goal, but give a warning if they might have meant the target (if the BUILD
      # file exists).
      try:
        BuildFile.from_cache(get_buildroot(), spec)
        msg = (' Command-line argument "{spec}" is ambiguous, and was assumed to be a goal.'
               ' If this is incorrect, disambiguate it with the "--" argument to separate goals'
               ' from targets.')
        logger.warning(msg.format(spec=spec))
      except MissingAddressError: pass # Awesome, it's unambiguous.
      return False

    for i, arg in enumerate(args):
      if not arg.startswith('-'):
        specs.add(arg) if is_spec(arg) else goals.add(arg)
      elif '--' == arg:
        if specs:
          raise GoalRunner.IntermixedArgumentsError(
            'Cannot intermix targets with goals when using --. Targets should appear on the right')
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
    super(GoalRunner, self).__init__(*args, **kwargs)

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

    goals, specs = GoalRunner.parse_args(non_help_args)
    if show_help:
      print_help(goals)
      sys.exit(0)

    self.requested_goals = goals

    # Bootstrap user goals by loading any BUILD files implied by targets.
    with self.run_tracker.new_workunit(name='setup', labels=[WorkUnit.SETUP]):

      # HACK: We need to parse the options now to get at the --exclude-targets-regexp option but the
      # options haven't been parsed yet.  If we call parser.parse_args, we end up with duplicate
      # option values later on. Makeing a copy of the parser object didn't work.
      def _get_target_excludes(args):
        results=[]
        flag='--exclude-target-regexp='
        for arg in args:
          if arg.startswith(flag):
            results.append(arg[len(flag):])
        return results

      self._spec_parser = CmdLineSpecParser(self.root_dir, self.address_mapper,
                                            target_excludes_opts=_get_target_excludes(args))
      with self.run_tracker.new_workunit(name='parse', labels=[WorkUnit.SETUP]):
        for spec in specs:
          for address in self._spec_parser.parse_addresses(spec):
            self.build_graph.inject_address_closure(address)
            self.targets.append(self.build_graph.get_target(address))
    self.goals = [Goal.by_name(goal) for goal in goals]

    rcfiles = self.config.getdefault('rcfiles', type=list,
                                     default=['/etc/pantsrc', '~/.pants.rc'])
    if rcfiles:
      rcfile = RcFile(rcfiles, default_prepend=False, process_default=True)

      # Break down the goals specified on the command line to the full set that will be run so we
      # can apply default flags to inner goal nodes.  Also break down goals by Task subclass and
      # register the task class hierarchy fully qualified names so we can apply defaults to
      # baseclasses.

      sections = OrderedSet()
      for goal in Engine.execution_order(self.goals):
        for task_name in goal.ordered_task_names():
          sections.add(task_name)
          task_type = goal.task_type_by_name(task_name)
          for clazz in task_type.mro():
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

    Goal.setup_parser(parser, args, self.goals)

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

    # Print some debugging that was waiting for the logger to be initialized.
    self._spec_parser.log_excludes_info(log)

    # Update the reporting settings, now that we have flags etc.
    def is_quiet_task():
      for goal in self.goals:
        if goal.has_task_of_type(QuietTaskMixin):
          return True
      return False

    is_explain = self.options.explain
    update_reporting(self.options, is_quiet_task() or is_explain, self.run_tracker)

    context = Context(
      config=self.config,
      options=self.options,
      run_tracker=self.run_tracker,
      target_roots=self.targets,
      requested_goals=self.requested_goals,
      build_graph=self.build_graph,
      build_file_parser=self.build_file_parser,
      address_mapper=self.address_mapper,
      lock=lock)

    unknown = []
    for goal in self.goals:
      if not goal.ordered_task_names():
        unknown.append(goal)

    if unknown:
      context.log.error('Unknown goal(s): %s\n' % ' '.join(goal.name for goal in unknown))
      return 1

    engine = RoundEngine()
    return engine.execute(context, self.goals)

  def cleanup(self):
    # TODO: This is JVM-specific and really doesn't belong here.
    # TODO: Make this more selective? Only kill nailguns that affect state? E.g., checkstyle
    # may not need to be killed.
    NailgunTask.killall(log.info)
    sys.exit(1)
