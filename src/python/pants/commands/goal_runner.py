# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
from contextlib import contextmanager
import inspect
import logging
import os
import re
import sys
import traceback

from twitter.common import log
from twitter.common.lang import Compatibility
from twitter.common.log.options import LogOptions

from pants.backend.core.tasks.task import QuietTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask  # XXX(pl)
from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.config import Config
from pants.base.workunit import WorkUnit
from pants.commands.command import Command
from pants.engine.round_engine import RoundEngine
from pants.goal.context import Context
from pants.goal.error import GoalError
from pants.goal.initialize_reporting import update_reporting
from pants.goal.goal import Goal
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.global_options import register_global_options
from pants.util.dirutil import safe_mkdir


StringIO = Compatibility.StringIO


class GoalRunner(Command):
  """Lists installed goals or else executes a named goal."""

  class IntermixedArgumentsError(GoalError):
    pass

  __command__ = 'goal'
  output = None

  def __init__(self, *args, **kwargs):
    self.targets = []
    known_scopes = ['']
    for goal in Goal.all():
      # Note that enclosing scopes will appear before scopes they enclose.
      known_scopes.extend(filter(None, goal.known_scopes()))

    self.new_options = OptionsBootstrapper().get_full_options(known_scopes=known_scopes)
    self.config = Config.from_cache()  # Get the bootstrapped version.
    super(GoalRunner, self).__init__(*args, needs_old_options=False, **kwargs)

  def get_spec_excludes(self):
    # Note: Only call after register_options() has been called.
    return [os.path.join(self.root_dir, spec_exclude)
            for spec_exclude in self.new_options.for_global_scope().spec_excludes]

  @property
  def global_options(self):
    return self.new_options.for_global_scope()

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

  def register_options(self):
    # Add a 'bootstrap' attribute to the register function, so that register_global can
    # access the bootstrap option values.
    def register_global(*args, **kwargs):
      return self.new_options.register_global(*args, **kwargs)
    register_global.bootstrap = self.new_options.bootstrap_option_values()
    register_global_options(register_global)
    for goal in Goal.all():
      goal.register_options(self.new_options)

  def setup_parser(self, parser, args):
    if not args:
      args.append('help')

    logger = logging.getLogger(__name__)

    goals = self.new_options.goals
    specs = self.new_options.target_specs
    fail_fast = self.new_options.for_global_scope().fail_fast

    for goal in goals:
      if BuildFile.from_cache(get_buildroot(), goal, must_exist=False).exists():
        logger.warning(" Command-line argument '{0}' is ambiguous and was assumed to be "
                       "a goal. If this is incorrect, disambiguate it with ./{0}.".format(goal))

    if self.new_options.is_help:
      self.new_options.print_help(goals=goals)
      sys.exit(0)

    self.requested_goals = goals

    with self.run_tracker.new_workunit(name='setup', labels=[WorkUnit.SETUP]):
      spec_parser = CmdLineSpecParser(self.root_dir, self.address_mapper,
                                      spec_excludes=self.get_spec_excludes())
      with self.run_tracker.new_workunit(name='parse', labels=[WorkUnit.SETUP]):
        for spec in specs:
          for address in spec_parser.parse_addresses(spec, fail_fast):
            self.build_graph.inject_address_closure(address)
            self.targets.append(self.build_graph.get_target(address))
    self.goals = [Goal.by_name(goal) for goal in goals]

  def run(self):
    # TODO(John Sirois): Consider moving to straight python logging.  The divide between the
    # context/work-unit logging and standard python logging doesn't buy us anything.

    # Enable standard python logging for code with no handle to a context/work-unit.
    if self.global_options.level:
      LogOptions.set_stderr_log_level((self.global_options.level or 'info').upper())
      logdir = self.global_options.logdir or self.config.get('goals', 'logdir', default=None)
      if logdir:
        safe_mkdir(logdir)
        LogOptions.set_log_dir(logdir)

        prev_log_level = None
        # If quiet, temporarily change stderr log level to kill init's output.
        if self.global_options.quiet:
          prev_log_level = LogOptions.loglevel_name(LogOptions.stderr_log_level())
          # loglevel_name can fail, so only change level if we were able to get the current one.
          if prev_log_level is not None:
            LogOptions.set_stderr_log_level(LogOptions._LOG_LEVEL_NONE_KEY)

        log.init('goals')

        if prev_log_level is not None:
          LogOptions.set_stderr_log_level(prev_log_level)
      else:
        log.init()

    # Update the reporting settings, now that we have flags etc.
    def is_quiet_task():
      for goal in self.goals:
        if goal.has_task_of_type(QuietTaskMixin):
          return True
      return False

    # Target specs are mapped to the patterns which match them, if any. This variable is a key for
    # specs which don't match any exclusion regexes. We know it won't already be in the list of
    # patterns, because the asterisks in its name make it an invalid regex.
    _UNMATCHED_KEY = '** unmatched **'

    def targets_by_pattern(targets, patterns):
      mapping = defaultdict(list)
      for target in targets:
        matched_pattern = None
        for pattern in patterns:
          if re.search(pattern, target.address.spec) is not None:
            matched_pattern = pattern
            break
        if matched_pattern is None:
          mapping[_UNMATCHED_KEY].append(target)
        else:
          mapping[matched_pattern].append(target)
      return mapping

    is_explain = self.global_options.explain
    update_reporting(self.global_options, is_quiet_task() or is_explain, self.run_tracker)

    if self.global_options.exclude_target_regexp:
      excludes = self.global_options.exclude_target_regexp
      log.debug('excludes:\n  {excludes}'.format(excludes='\n  '.join(excludes)))
      by_pattern = targets_by_pattern(self.targets, excludes)
      self.targets = by_pattern[_UNMATCHED_KEY]
      # The rest of this if-statement is just for debug logging.
      log.debug('Targets after excludes: {targets}'.format(
          targets=', '.join(t.address.spec for t in self.targets)))
      excluded_count = sum(len(by_pattern[p]) for p in excludes)
      log.debug('Excluded {count} target{plural}.'.format(count=excluded_count,
          plural=('s' if excluded_count != 1 else '')))
      for pattern in excludes:
        log.debug('Targets excluded by pattern {pattern}\n  {targets}'.format(pattern=pattern,
            targets='\n  '.join(t.address.spec for t in by_pattern[pattern])))

    context = Context(
      config=self.config,
      new_options=self.new_options,
      run_tracker=self.run_tracker,
      target_roots=self.targets,
      requested_goals=self.requested_goals,
      build_graph=self.build_graph,
      build_file_parser=self.build_file_parser,
      address_mapper=self.address_mapper,
      spec_excludes=self.get_spec_excludes()
    )

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
