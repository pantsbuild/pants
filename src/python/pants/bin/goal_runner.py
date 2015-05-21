# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import logging.config
import sys

import pkg_resources

from pants.backend.core.tasks.task import QuietTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask  # XXX(pl)
from pants.base.build_environment import get_buildroot, get_scm
from pants.base.build_file import FilesystemBuildFile
from pants.base.build_file_address_mapper import BuildFileAddressMapper
from pants.base.build_file_parser import BuildFileParser
from pants.base.build_graph import BuildGraph
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.extension_loader import load_plugins_and_backends
from pants.base.scm_build_file import ScmBuildFile
from pants.base.workunit import WorkUnit
from pants.engine.round_engine import RoundEngine
from pants.goal.context import Context
from pants.goal.goal import Goal
from pants.goal.run_tracker import RunTracker
from pants.logging.setup import setup_logging
from pants.option.global_options import register_global_options
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.reporting.report import Report
from pants.reporting.reporting import Reporting
from pants.subsystem.subsystem import Subsystem


logger = logging.getLogger(__name__)


class SourceRootBootstrapper(Subsystem):
  @classmethod
  def scope_qualifier(cls):
    # This is an odd name, but we maintain the legacy scope until we can kill this subsystem
    # outright.
    return 'goals'

  @classmethod
  def register_options(cls, register):
    super(SourceRootBootstrapper, cls).register_options(register)
    # TODO: Get rid of bootstrap buildfiles in favor of source root registration at backend load
    # time.
    register('--bootstrap-buildfiles', advanced=True, type=Options.list, default=[],
             help='Initialize state by evaluating these buildfiles.')

  def bootstrap(self, address_mapper, build_file_parser):
    for path in self.get_options().bootstrap_buildfiles:
      build_file = address_mapper.from_cache(root_dir=build_file_parser.root_dir, relpath=path)
      # TODO(pl): This is an unfortunate interface leak, but I don't think
      # in the long run that we should be relying on "bootstrap" BUILD files
      # that do nothing except modify global state.  That type of behavior
      # (e.g. source roots, goal registration) should instead happen in
      # project plugins, or specialized configuration files.
      build_file_parser.parse_build_file_family(build_file)


class GoalRunner(object):
  """Lists installed goals or else executes a named goal."""

  def __init__(self, root_dir):
    """
    :param root_dir: The root directory of the pants workspace.
    """
    self.root_dir = root_dir

  @property
  def subsystems(self):
    # Subsystems used outside of any task.
    return SourceRootBootstrapper, Reporting, RunTracker

  def setup(self):
    options_bootstrapper = OptionsBootstrapper()
    bootstrap_options = options_bootstrapper.get_bootstrap_options()

    # Get logging setup prior to loading backends so that they can log as needed.
    self._setup_logging(bootstrap_options.for_global_scope())

    # Add any extra paths to python path (eg for loading extra source backends)
    for path in bootstrap_options.for_global_scope().pythonpath:
      sys.path.append(path)
      pkg_resources.fixup_namespace_packages(path)

    # Load plugins and backends.
    plugins = bootstrap_options.for_global_scope().plugins
    backend_packages = bootstrap_options.for_global_scope().backend_packages
    build_configuration = load_plugins_and_backends(plugins, backend_packages)

    # Now that plugins and backends are loaded, we can gather the known scopes.
    self.targets = []

    known_scopes = ['']

    # Add scopes for global subsystem instances.
    global_subsystems = (set(self.subsystems) |
                         Goal.global_subsystem_types() |
                         build_configuration.subsystem_types())
    for subsystem_type in global_subsystems:
      known_scopes.append(subsystem_type.qualify_scope(Options.GLOBAL_SCOPE))

    # Add scopes for all tasks in all goals.
    for goal in Goal.all():
      # Note that enclosing scopes will appear before scopes they enclose.
      known_scopes.extend(filter(None, goal.known_scopes()))

    # Now that we have the known scopes we can get the full options.
    self.options = options_bootstrapper.get_full_options(known_scopes=known_scopes)
    self.register_subsystem_options(global_subsystems)

    # Make the options values available to all subsystems.
    Subsystem._options = self.options

    # Now that we have options we can instantiate subsystems.
    self.run_tracker = RunTracker.global_instance()
    self.reporting = Reporting.global_instance()
    report = self.reporting.initial_reporting(self.run_tracker)
    self.run_tracker.start(report)
    url = self.run_tracker.run_info.get_info('report_url')
    if url:
      self.run_tracker.log(Report.INFO, 'See a report at: {}'.format(url))
    else:
      self.run_tracker.log(Report.INFO, '(To run a reporting server: ./pants server)')

    self.build_file_parser = BuildFileParser(build_configuration=build_configuration,
                                             root_dir=self.root_dir,
                                             run_tracker=self.run_tracker)

    rev = self.options.for_global_scope().build_file_rev
    if rev:
      ScmBuildFile.set_rev(rev)
      ScmBuildFile.set_scm(get_scm())
      build_file_type = ScmBuildFile
    else:
      build_file_type = FilesystemBuildFile
    self.address_mapper = BuildFileAddressMapper(self.build_file_parser, build_file_type)
    self.build_graph = BuildGraph(run_tracker=self.run_tracker,
                                  address_mapper=self.address_mapper)

    # TODO(John Sirois): Kill when source root registration is lifted out of BUILD files.
    with self.run_tracker.new_workunit(name='bootstrap', labels=[WorkUnit.SETUP]):
      source_root_bootstrapper = SourceRootBootstrapper.global_instance()
      source_root_bootstrapper.bootstrap(self.address_mapper, self.build_file_parser)

    self._expand_goals_and_specs()

    # Now that we've parsed the bootstrap BUILD files, and know about the SCM system.
    self.run_tracker.run_info.add_scm_info()

  @property
  def spec_excludes(self):
    # Note: Only call after register_options() has been called.
    return self.options.for_global_scope().spec_excludes

  @property
  def global_options(self):
    return self.options.for_global_scope()

  def register_subsystem_options(self, global_subsystems):
    # Standalone global options.
    register_global_options(self.options.registration_function_for_global_scope())

    # Options for global-level subsystems.
    for subsystem_type in global_subsystems:
      subsystem_type.register_options_on_scope(self.options, Options.GLOBAL_SCOPE)

    # TODO(benjy): Should Goals be subsystems? Or should the entire goal-running mechanism
    # be a subsystem?
    for goal in Goal.all():
      # Register task options (including per-task subsystem options).
      goal.register_options(self.options)

  def _expand_goals_and_specs(self):
    goals = self.options.goals
    specs = self.options.target_specs
    fail_fast = self.options.for_global_scope().fail_fast

    for goal in goals:
      if self.address_mapper.from_cache(get_buildroot(), goal, must_exist=False).file_exists():
        logger.warning(" Command-line argument '{0}' is ambiguous and was assumed to be "
                       "a goal. If this is incorrect, disambiguate it with ./{0}.".format(goal))

    if self.options.print_help_if_requested():
      sys.exit(0)

    self.requested_goals = goals

    with self.run_tracker.new_workunit(name='setup', labels=[WorkUnit.SETUP]):
      spec_parser = CmdLineSpecParser(self.root_dir, self.address_mapper,
                                      spec_excludes=self.spec_excludes,
                                      exclude_target_regexps=self.global_options.exclude_target_regexp)
      with self.run_tracker.new_workunit(name='parse', labels=[WorkUnit.SETUP]):
        for spec in specs:
          for address in spec_parser.parse_addresses(spec, fail_fast):
            self.build_graph.inject_address_closure(address)
            self.targets.append(self.build_graph.get_target(address))
    self.goals = [Goal.by_name(goal) for goal in goals]

  def run(self):
    def fail():
      self.run_tracker.set_root_outcome(WorkUnit.FAILURE)

    kill_nailguns = self.options.for_global_scope().kill_nailguns
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
        NailgunTask.killall()
    return result

  def _do_run(self):
    # Update the reporting settings, now that we have flags etc.
    def is_quiet_task():
      for goal in self.goals:
        if goal.has_task_of_type(QuietTaskMixin):
          return True
      return False

    is_explain = self.global_options.explain
    self.reporting.update_reporting(self.global_options,
                                    is_quiet_task() or is_explain,
                                    self.run_tracker)

    context = Context(
      options=self.options,
      run_tracker=self.run_tracker,
      target_roots=self.targets,
      requested_goals=self.requested_goals,
      build_graph=self.build_graph,
      build_file_parser=self.build_file_parser,
      address_mapper=self.address_mapper,
      spec_excludes=self.spec_excludes
    )

    unknown = []
    for goal in self.goals:
      if not goal.ordered_task_names():
        unknown.append(goal)

    if unknown:
      context.log.error('Unknown goal(s): {}\n'.format(' '.join(goal.name for goal in unknown)))
      return 1

    engine = RoundEngine()
    return engine.execute(context, self.goals)

  def _setup_logging(self, global_options):
    # NB: quiet help says 'Squelches all console output apart from errors'.
    level = 'ERROR' if global_options.quiet else global_options.level.upper()

    setup_logging(level, log_dir=global_options.logdir)
