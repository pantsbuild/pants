# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import logging
import os
import re
import sys
from pants.base.build_graph import BuildGraph

from twitter.common import log
from twitter.common.lang import Compatibility
from twitter.common.log.options import LogOptions

from pants.backend.core.tasks.task import QuietTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask  # XXX(pl)
from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.base.build_file_address_mapper import BuildFileAddressMapper
from pants.base.build_file_parser import BuildFileParser
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.config import Config
from pants.base.extension_loader import load_plugins_and_backends
from pants.base.workunit import WorkUnit
from pants.engine.round_engine import RoundEngine
from pants.goal.context import Context
from pants.goal.initialize_reporting import update_reporting, initial_reporting
from pants.goal.goal import Goal
from pants.goal.run_tracker import RunTracker
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.global_options import register_global_options
from pants.reporting.report import Report
from pants.util.dirutil import safe_mkdir


StringIO = Compatibility.StringIO


class GoalRunner(object):
  """Lists installed goals or else executes a named goal."""

  def __init__(self, root_dir):
    """
    :param root_dir: The root directory of the pants workspace.
    """
    self.root_dir = root_dir

  def setup(self):
    options_bootstrapper = OptionsBootstrapper()

    # Force config into the cache so we (and plugin/backend loading code) can use it.
    # TODO: Plumb options in explicitly.
    options_bootstrapper.get_bootstrap_options()
    self.config = Config.from_cache()

    # Load plugins and backends.
    backend_packages = self.config.getlist('backends', 'packages', [])
    plugins = self.config.getlist('backends', 'plugins', [])
    build_configuration = load_plugins_and_backends(plugins, backend_packages)

    # Now that plugins and backends are loaded, we can gather the known scopes.
    self.targets = []
    known_scopes = ['']
    for goal in Goal.all():
      # Note that enclosing scopes will appear before scopes they enclose.
      known_scopes.extend(filter(None, goal.known_scopes()))

    # Now that we have the known scopes we can get the full options.
    self.new_options = options_bootstrapper.get_full_options(known_scopes=known_scopes)
    self.register_options()

    self.run_tracker = RunTracker.from_config(self.config)
    report = initial_reporting(self.config, self.run_tracker)
    self.run_tracker.start(report)
    url = self.run_tracker.run_info.get_info('report_url')
    if url:
      self.run_tracker.log(Report.INFO, 'See a report at: %s' % url)
    else:
      self.run_tracker.log(Report.INFO, '(To run a reporting server: ./pants goal server)')

    self.build_file_parser = BuildFileParser(build_configuration=build_configuration,
                                             root_dir=self.root_dir,
                                             run_tracker=self.run_tracker)
    self.address_mapper = BuildFileAddressMapper(self.build_file_parser)
    self.build_graph = BuildGraph(run_tracker=self.run_tracker,
                                  address_mapper=self.address_mapper)

    with self.run_tracker.new_workunit(name='bootstrap', labels=[WorkUnit.SETUP]):
      # construct base parameters to be filled in for BuildGraph
      for path in self.config.getlist('goals', 'bootstrap_buildfiles', default=[]):
        build_file = BuildFile.from_cache(root_dir=self.root_dir, relpath=path)
        # TODO(pl): This is an unfortunate interface leak, but I don't think
        # in the long run that we should be relying on "bootstrap" BUILD files
        # that do nothing except modify global state.  That type of behavior
        # (e.g. source roots, goal registration) should instead happen in
        # project plugins, or specialized configuration files.
        self.build_file_parser.parse_build_file_family(build_file)

    # Now that we've parsed the bootstrap BUILD files, and know about the SCM system.
    self.run_tracker.run_info.add_scm_info()

    self._expand_goals_and_specs()

  def get_spec_excludes(self):
    # Note: Only call after register_options() has been called.
    return [os.path.join(self.root_dir, spec_exclude)
            for spec_exclude in self.new_options.for_global_scope().spec_excludes]

  @property
  def global_options(self):
    return self.new_options.for_global_scope()

  def register_options(self):
    # Add a 'bootstrap' attribute to the register function, so that register_global can
    # access the bootstrap option values.
    def register_global(*args, **kwargs):
      return self.new_options.register_global(*args, **kwargs)
    register_global.bootstrap = self.new_options.bootstrap_option_values()
    register_global_options(register_global)
    for goal in Goal.all():
      goal.register_options(self.new_options)

  def _expand_goals_and_specs(self):
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
    def fail():
      self.run_tracker.set_root_outcome(WorkUnit.FAILURE)

    kill_nailguns = self.new_options.for_global_scope().kill_nailguns
    try:
      result = self._do_run()
      if result:
        fail()
    except KeyboardInterrupt:
      fail()
      # On ctrl-c we always kill nailguns, otherwise they might keep running
      # some heavyweight compilation and gum up the system during a subsequent run.
      kill_nailguns = True
      raise
    except Exception:
      fail()
      raise
    finally:
      self.run_tracker.end()
      # Must kill nailguns only after run_tracker.end() is called, otherwise there may still
      # be pending background work that needs a nailgun.
      if kill_nailguns:
        # TODO: This is JVM-specific and really doesn't belong here.
        # TODO: Make this more selective? Only kill nailguns that affect state?
        # E.g., checkstyle may not need to be killed.
        NailgunTask.killall(log.info)
    return result

  def _do_run(self):
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
