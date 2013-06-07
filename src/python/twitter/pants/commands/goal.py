# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import daemon

import errno
import inspect
import multiprocessing
import os
import sys
import signal
import socket
import time
import traceback

from contextlib import contextmanager
from optparse import Option, OptionParser

from twitter.common import log
from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir, safe_rmtree
from twitter.common.lang import Compatibility
from twitter.pants import get_buildroot, goal, group, has_sources, is_apt
from twitter.pants.base import Address, BuildFile, Config, ParseContext, Target
from twitter.pants.base.rcfile import RcFile
from twitter.pants.commands import Command
from twitter.pants.goal.initialize_reporting import update_reporting
from twitter.pants.goal.workunit import WorkUnit
from twitter.pants.reporting.reporting_server import ReportingServer
from twitter.pants.tasks import Task, TaskError
from twitter.pants.tasks.check_exclusives import CheckExclusives
from twitter.pants.tasks.console_task import ConsoleTask
from twitter.pants.tasks.nailgun_task import NailgunTask

from twitter.pants.goal import Context, GoalError, Phase


try:
  import colors
except ImportError:
  turn_off_colored_logging = True
else:
  turn_off_colored_logging = False

StringIO = Compatibility.StringIO


class List(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("all"), dest="goal_list_all", default=False, action="store_true",
                            help="[%default] List all goals even if no description is available.")

  def execute(self, targets):
    self.context.lock.release()
    print('Installed goals:')
    documented_rows = []
    undocumented = []
    max_width = 0
    for phase, _ in Phase.all():
      if phase.description:
        documented_rows.append((phase.name, phase.description))
        max_width = max(max_width, len(phase.name))
      elif self.context.options.goal_list_all:
        undocumented.append(phase.name)
    for name, description in documented_rows:
      print('  %s: %s' % (name.rjust(max_width), description))
    if undocumented:
      print('\nUndocumented goals:\n  %s' % ' '.join(undocumented))


goal(name='goals', action=List).install().with_description('List all documented goals.')


class Help(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    default = None
    if len(args) > 1 and (not args[1].startswith('-')):
      default = args[1]
      del args[1]
    option_group.add_option(mkflag("goal"), dest="help_goal", default=default)

  def execute(self, targets):
    goal = self.context.options.help_goal
    if goal is None:
      return self.list_goals('You must supply a goal name to provide help for.')
    phase = Phase(goal)
    if not phase.goals():
      return self.list_goals('Goal %s is unknown.' % goal)

    parser = OptionParser()
    parser.set_usage('%s goal %s ([target]...)' % (sys.argv[0], goal))
    parser.epilog = phase.description
    Goal.add_global_options(parser)
    Phase.setup_parser(parser, [], [phase])
    parser.parse_args(['--help'])

  def list_goals(self, message):
    print(message)
    print()
    return Phase.execute(self.context, 'goals')

goal(name='help', action=Help).install().with_description('Provide help for the specified goal.')


def _set_bool(option, opt_str, value, parser):
  setattr(parser.values, option.dest, not opt_str.startswith("--no"))


class SpecParser(object):
  """Parses goal target specs; either simple target addresses or else sibling (:) or descendant
  (::) selector forms
  """

  def __init__(self, root_dir):
    self._root_dir = root_dir

  def _get_dir(self, spec):
    path = spec.split(':', 1)[0]
    if os.path.isdir(path):
      return path
    else:
      if os.path.isfile(path):
        return os.path.dirname(path)
      else:
        return spec

  def _parse_addresses(self, spec):
    if spec.endswith('::'):
      dir = self._get_dir(spec[:-len('::')])
      for buildfile in BuildFile.scan_buildfiles(self._root_dir, os.path.join(self._root_dir, dir)):
        for address in Target.get_all_addresses(buildfile):
          yield address
    elif spec.endswith(':'):
      dir = self._get_dir(spec[:-len(':')])
      for address in Target.get_all_addresses(BuildFile(self._root_dir, dir)):
        yield address
    else:
      yield Address.parse(self._root_dir, spec)

  def parse(self, spec):
    """Parses the given target spec into one or more targets.

    Returns a generator of target, address pairs in which the target may be None if the address
    points to a non-existent target.
    """
    for address in self._parse_addresses(spec):
      target = Target.get(address)
      yield target, address


class Goal(Command):
  """Lists installed goals or else executes a named goal."""

  __command__ = 'goal'

  GLOBAL_OPTIONS = [
    Option("-t", "--timeout", dest="conn_timeout", type='int',
           default=Config.load().getdefault('connection_timeout'),
           help="Number of seconds to wait for http connections."),
    Option("-x", "--time", action="store_true", dest="time", default=False,
           help="Times goal phases and outputs a report."),
    Option("-e", "--explain", action="store_true", dest="explain", default=False,
           help="Explain the execution of goals."),
    Option("-k", "--kill-nailguns", action="store_true", dest="cleanup_nailguns", default=False,
           help="Kill nailguns before exiting"),
    Option("-d", "--logdir", dest="logdir",
           help="[%default] Forks logs to files under this directory."),
    Option("-l", "--level", dest="log_level", type="choice", choices=['debug', 'info', 'warn'],
           help="[info] Sets the logging level to one of 'debug', 'info' or 'warn'."
                "if set."),
    Option("-q", "--quiet", action="store_true", dest="quiet", default=False,
           help="Squelches all console output apart from errors."),
    Option("--no-colors", dest="no_color", action="store_true", default=turn_off_colored_logging,
           help="Do not colorize log messages."),
    Option("-n", "--dry-run", action="store_true", dest="dry_run", default=False,
      help="Print the commands that would be run, without actually running them."),
    Option("--read-from-artifact-cache", "--no-read-from-artifact-cache", action="callback",
      callback=_set_bool, dest="read_from_artifact_cache", default=False,
      help="Whether to read artifacts from cache instead of building them, when possible."),
    Option("--write-to-artifact-cache", "--no-write-to-artifact-cache", action="callback",
      callback=_set_bool, dest="write_to_artifact_cache", default=False,
      help="Whether to write artifacts to cache ."),
    Option("--verify-artifact-cache", "--no-verify-artifact-cache", action="callback",
      callback=_set_bool, dest="verify_artifact_cache", default=False,
      help="Whether to verify that cached artifacts are identical after rebuilding them."),
    Option("--all", dest="target_directory", action="append",
           help="DEPRECATED: Use [dir]: with no flag in a normal target position on the command "
                "line. (Adds all targets found in the given directory's BUILD file. Can be "
                "specified more than once.)"),
    Option("--all-recursive", dest="recursive_directory", action="append",
           help="DEPRECATED: Use [dir]:: with no flag in a normal target position on the command "
                "line. (Adds all targets found recursively under the given directory. Can be "
                "specified more than once to add more than one root target directory to scan.)"),
  ]

  output = None

  @staticmethod
  def add_global_options(parser):
    for option in Goal.GLOBAL_OPTIONS:
      parser.add_option(option)

  @staticmethod
  def parse_args(args):
    goals = OrderedSet()
    specs = OrderedSet()
    help = False
    explicit_multi = False

    def is_spec(spec):
      return os.sep in spec or ':' in spec

    for i, arg in enumerate(args):
      help = help or 'help' == arg
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
      spec_offset = len(goals) + 1 if help else len(goals)
      specs.update(arg for arg in args[spec_offset:] if not arg.startswith('-'))

    return goals, specs

  @classmethod
  def serialized(cls):
    # Goal serialization is now handled in goal execution during group processing.
    # The goal command doesn't need to hold the serialization lock; individual goals will
    # acquire the lock if they need to be serialized.
    return False

  def __init__(self, run_tracker, root_dir, parser, args):
    self.targets = []
    Command.__init__(self, run_tracker, root_dir, parser, args)

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
    Goal.add_global_options(parser)

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
      args.append('goals')

    if len(args) == 1 and args[0] in set(['-h', '--help', 'help']):
      def format_usage(usages):
        left_colwidth = 0
        for left, right in usages:
          left_colwidth = max(left_colwidth, len(left))
        lines = []
        for left, right in usages:
          lines.append('  %s%s%s' % (left, ' ' * (left_colwidth - len(left) + 1), right))
        return '\n'.join(lines)

      usages = [
        ("%prog goal goals ([spec]...)", Phase('goals').description),
        ("%prog goal help [goal] ([spec]...)", Phase('help').description),
        ("%prog goal [goal] [spec]...", "Attempt goal against one or more targets."),
        ("%prog goal [goal] ([goal]...) -- [spec]...", "Attempts all the specified goals."),
      ]
      parser.set_usage("\n%s" % format_usage(usages))
      parser.epilog = ("Either lists all installed goals, provides extra help for a goal or else "
                       "attempts to achieve the specified goal for the listed targets." """
                       Note that target specs accept two special forms:
                         [dir]:  to include all targets in the specified directory
                         [dir]:: to include all targets found in all BUILD files recursively under
                                 the directory""")

      parser.print_help()
      sys.exit(0)
    else:
      goals, specs = Goal.parse_args(args)
      self.requested_goals = goals

      with self.run_tracker.new_workunit(name='setup', labels=[WorkUnit.SETUP]):
        # Bootstrap goals by loading any configured bootstrap BUILD files
        with self.check_errors('The following bootstrap_buildfiles cannot be loaded:') as error:
          with self.run_tracker.new_workunit(name='bootstrap', labels=[WorkUnit.SETUP]):
            for path in self.config.getlist('goals', 'bootstrap_buildfiles', default = []):
              try:
                buildfile = BuildFile(get_buildroot(), os.path.relpath(path, get_buildroot()))
                ParseContext(buildfile).parse()
              except (TypeError, ImportError, TaskError, GoalError):
                error(path, include_traceback=True)
              except (IOError, SyntaxError):
                error(path)
        # Now that we've parsed the bootstrap BUILD files, and know about the SCM system.
        self.run_tracker.run_info.add_scm_info()

        # Bootstrap user goals by loading any BUILD files implied by targets.
        spec_parser = SpecParser(self.root_dir)
        with self.check_errors('The following targets could not be loaded:') as error:
          with self.run_tracker.new_workunit(name='parse', labels=[WorkUnit.SETUP]):
            for spec in specs:
              try:
                for target, address in spec_parser.parse(spec):
                  if target:
                    self.targets.append(target)
                    # Force early BUILD file loading if this target is an alias that expands
                    # to others.
                    unused = list(target.resolve())
                  else:
                    siblings = Target.get_all_addresses(address.buildfile)
                    prompt = 'did you mean' if len(siblings) == 1 else 'maybe you meant one of these'
                    error('%s => %s?:\n    %s' % (address, prompt,
                                                  '\n    '.join(str(a) for a in siblings)))
              except (TypeError, ImportError, TaskError, GoalError):
                error(spec, include_traceback=True)
              except (IOError, SyntaxError):
                error(spec)

      self.phases = [Phase(goal) for goal in goals]

      rcfiles = self.config.getdefault('rcfiles', type=list, default=[])
      if rcfiles:
        rcfile = RcFile(rcfiles, default_prepend=False, process_default=True)

        # Break down the goals specified on the command line to the full set that will be run so we
        # can apply default flags to inner goal nodes.  Also break down goals by Task subclass and
        # register the task class hierarchy fully qualified names so we can apply defaults to
        # baseclasses.

        all_goals = Phase.execution_order(Phase(goal) for goal in goals)
        sections = OrderedSet()
        for goal in all_goals:
          sections.add(goal.name)
          for clazz in goal.task_type.mro():
            if clazz == Task:
              break
            sections.add('%s.%s' % (clazz.__module__, clazz.__name__))

        augmented_args = rcfile.apply_defaults(sections, args)
        if augmented_args != args:
          del args[:]
          args.extend(augmented_args)
          sys.stderr.write("(using pantsrc expansion: pants goal %s)\n" % ' '.join(augmented_args))

      Phase.setup_parser(parser, args, self.phases)

  def run(self, lock):
    # Update the reporting settings, now that we have flags etc.
    def is_console_task():
      for phase in self.phases:
        for goal in phase.goals():
          if issubclass(goal.task_type, ConsoleTask):
            return True
      return False

    update_reporting(self.options, is_console_task(), self.run_tracker)

    if self.options.dry_run:
      print '****** Dry Run ******'

    context = Context(
      self.config,
      self.options,
      self.run_tracker,
      self.targets,
      requested_goals=self.requested_goals,
      lock=lock)

    # TODO: Time to get rid of this hack.
    if self.options.recursive_directory:
      context.log.warn(
        '--all-recursive is deprecated, use a target spec with the form [dir]:: instead')
      for dir in self.options.recursive_directory:
        self.add_target_recursive(dir)

    if self.options.target_directory:
      context.log.warn('--all is deprecated, use a target spec with the form [dir]: instead')
      for dir in self.options.target_directory:
        self.add_target_directory(dir)

    unknown = []
    for phase in self.phases:
      if not phase.goals():
        unknown.append(phase)

    if unknown:
      print('Unknown goal(s): %s' % ' '.join(phase.name for phase in unknown))
      print('')
      return Phase.execute(context, 'goals')

    ret = Phase.attempt(context, self.phases)

    if self.options.cleanup_nailguns or self.config.get('nailgun', 'autokill', default = False):
      if log:
        log.debug('auto-killing nailguns')
      if NailgunTask.killall:
        NailgunTask.killall(log)

    return ret

  def cleanup(self):
    # TODO: Make this more selective? Only kill nailguns that affect state? E.g., checkstyle
    # may not need to be killed.
    if NailgunTask.killall:
      NailgunTask.killall(log)
    sys.exit(1)


# Install all default pants provided goals
from twitter.pants import junit_tests
from twitter.pants.targets import (
  Benchmark,
  JavaLibrary,
  JvmBinary,
  ScalaLibrary,
  ScalaTests,
  ScalacPlugin)
from twitter.pants.tasks.antlr_gen import AntlrGen
from twitter.pants.tasks.benchmark_run import BenchmarkRun
from twitter.pants.tasks.binary_create import BinaryCreate
from twitter.pants.tasks.build_lint import BuildLint
from twitter.pants.tasks.bundle_create import BundleCreate
from twitter.pants.tasks.checkstyle import Checkstyle
from twitter.pants.tasks.extract import Extract
from twitter.pants.tasks.check_exclusives import CheckExclusives
from twitter.pants.tasks.filedeps import FileDeps
from twitter.pants.tasks.idl_resolve import IdlResolve
from twitter.pants.tasks.ivy_resolve import IvyResolve
from twitter.pants.tasks.jar_create import JarCreate
from twitter.pants.tasks.java_compile import JavaCompile
from twitter.pants.tasks.javadoc_gen import JavadocGen
from twitter.pants.tasks.scaladoc_gen import ScaladocGen
from twitter.pants.tasks.junit_run import JUnitRun
from twitter.pants.tasks.jvm_run import JvmRun
from twitter.pants.tasks.markdown_to_html import MarkdownToHtml
from twitter.pants.tasks.listtargets import ListTargets
from twitter.pants.tasks.pathdeps import PathDeps
from twitter.pants.tasks.prepare_resources import PrepareResources
from twitter.pants.tasks.protobuf_gen import ProtobufGen
from twitter.pants.tasks.scala_compile import ScalaCompile
from twitter.pants.tasks.scala_repl import ScalaRepl
from twitter.pants.tasks.specs_run import SpecsRun
from twitter.pants.tasks.thrift_gen import ThriftGen
from twitter.pants.tasks.scrooge_gen import ScroogeGen


class Invalidator(Task):
  def execute(self, targets):
    build_invalidator_dir = self.context.config.get('tasks', 'build_invalidator')
    safe_rmtree(build_invalidator_dir)
goal(name='invalidate', action=Invalidator).install().with_description('Invalidate all targets')

class ArtifactCacheWiper(Task):
  def execute(self, targets):
    artifact_cache_dir = self.context.config.get('tasks', 'artifact_cache')
    safe_rmtree(artifact_cache_dir)
goal(name='wipe-local-artifact-cache', action=ArtifactCacheWiper
).install().with_description('Delete all cached artifacts')

goal(
  name='clean-all',
  action=lambda ctx: safe_rmtree(ctx.config.getdefault('pants_workdir')),
  dependencies=['invalidate']
).install().with_description('Cleans all intermediate build output')


try:
  import daemon

  def async_safe_rmtree(root):
    if os.path.exists(root):
      new_path = root + '.deletable.%f' % time.time()
      os.rename(root, new_path)
      with daemon.DaemonContext():
        safe_rmtree(new_path)

  goal(
    name='clean-all-async',
    action=lambda ctx: async_safe_rmtree(ctx.config.getdefault('pants_workdir')),
    dependencies=['invalidate']
  ).install().with_description('Cleans all intermediate build output in a background process')
except ImportError:
  pass


if NailgunTask.killall:
  class NailgunKillall(Task):
    @classmethod
    def setup_parser(cls, option_group, args, mkflag):
      option_group.add_option(mkflag("everywhere"), dest="ng_killall_everywhere",
                              default=False, action="store_true",
                              help="[%default] Kill all nailguns servers launched by pants for "
                                   "all workspaces on the system.")

    def execute(self, targets):
      if NailgunTask.killall:
        NailgunTask.killall(self.context.log, everywhere=self.context.options.ng_killall_everywhere)

  ng_killall = goal(name='ng-killall', action=NailgunKillall)
  ng_killall.install().with_description('Kill any running nailgun servers spawned by pants.')

  ng_killall.install('clean-all', first=True)


def get_port_and_pidfile(context):
  port = context.options.port or context.config.getint('reporting', 'reporting_port')
  # We don't put the pidfile in .pants.d, because we want to find it even after a clean.
  # TODO: Fold pants.run and other pidfiles into here. Generalize the pidfile idiom into
  # some central library.
  pidfile = os.path.join(get_buildroot(), '.pids', 'port_%d.pid' % port)
  return port, pidfile

class RunServer(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("port"), dest="port", action="store", type="int", default=0,
      help="Serve on this port.")
    option_group.add_option(mkflag("allowed-clients"), dest="allowed_clients",
      default=["127.0.0.1"], action="append",
      help="Only requests from these IPs may access this server. Useful for temporarily showing " \
           "build results to a colleague. The special value ALL means any client may connect. " \
           "Use with caution, as your source code is exposed to all allowed clients!")

  def execute(self, targets):
    DONE = '__done_reporting'

    def run_server(reporting_queue):
      (port, pidfile) = get_port_and_pidfile(self.context)
      def write_pidfile():
        safe_mkdir(os.path.dirname(pidfile))
        with open(pidfile, 'w') as outfile:
          outfile.write(str(os.getpid()))

      def report_launch():
        reporting_queue.put(
          'Launching server with pid %d at http://localhost:%d' % (os.getpid(), port))
        show_latest_run_msg()

      def show_latest_run_msg():
        url = 'http://localhost:%d/run/latest' % port
        try:
          from colors import magenta
          url = magenta(url)
        except ImportError:
          pass
        reporting_queue.put('Automatically see latest run at %s' % url)

      def done_reporting():
        reporting_queue.put(DONE)

      try:
        # We mustn't block in the child, because the multiprocessing module enforces that the
        # parent either kills or joins to it. Instead we fork a grandchild that inherits the queue
        # but is allowed to block indefinitely on the server loop.
        if not os.fork():
          # Child process.
          info_dir = self.context.config.getdefault('info_dir')
          template_dir = self.context.config.get('reporting', 'reports_template_dir')
          assets_dir = self.context.config.get('reporting', 'reports_assets_dir')
          settings = ReportingServer.Settings(info_dir=info_dir, template_dir=template_dir,
                                              assets_dir=assets_dir, root=get_buildroot(),
                                              allowed_clients=self.context.options.allowed_clients)
          server = ReportingServer(port, settings)
          # Block forever here.
          server.start(run_before_blocking=[write_pidfile, report_launch, done_reporting])
      except socket.error, e:
        if e.errno == errno.EADDRINUSE:
          reporting_queue.put('Server already running at http://localhost:%d' % port)
          show_latest_run_msg()
          done_reporting()
          return
        else:
          done_reporting()
          raise
    # We do reporting on behalf of the child process (necessary, since reporting is buffered in a
    # background thread). We use multiprocessing.Process() to spawn the child so we can use that
    # module's inter-process Queue implementation.
    reporting_queue = multiprocessing.Queue()
    proc = multiprocessing.Process(target=run_server, args=[reporting_queue])
    proc.daemon = True
    proc.start()
    s = reporting_queue.get()
    while s != DONE:
      self.context.log.info(s)
      s = reporting_queue.get()
    # The child process is done reporting, and is now in the server loop, so we can proceed.

goal(
  name='server',
  action=RunServer,
).install().with_description('Run the pants reporting server.')

class KillServer(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("port"), dest="port", action="store", type="int", default=0,
      help="Serve on this port.")

  def execute(self, targets):
    (port, pidfile) = get_port_and_pidfile(self.context)
    if os.path.exists(pidfile):
      with open(pidfile, 'r') as infile:
        pidstr = infile.read()
      try:
        os.unlink(pidfile)
        pid = int(pidstr)
        os.kill(pid, signal.SIGKILL)
        self.context.log.info('Killed server with pid %d at http://localhost:%d\n' % (pid, port))
      except (ValueError, OSError):
        pass
    else:
      self.context.log.info('No server found.')

goal(
  name='killserver',
  action=KillServer,
).install().with_description('Kill the pants reporting server.')

# TODO(John Sirois): Resolve eggs
goal(
  name='ivy',
  action=IvyResolve,
  dependencies=['gen', 'check_exclusives']
).install('resolve').with_description('Resolves jar dependencies and produces dependency reports.')

goal(name='check_exclusives',
  dependencies=['gen'],
  action=CheckExclusives).install('check_exclusives').with_description(
  'Check exclusives declarations to verify that dependencies are consistent.')


goal(
  name='idl',
  action=IdlResolve,
).install('resolve-idl').with_description('Resolves idl jar dependencies.')

goal(
  name='extract',
  action=Extract,
).install('resolve-idl')

# TODO(John Sirois): gen attempted as the sole Goal should gen for all known gen types but
# recognize flags to narrow the gen set
goal(name='thrift', action=ThriftGen,
  dependencies=['resolve-idl']).install('gen').with_description('Generate code.')
goal(name='scrooge', action=ScroogeGen,
  dependencies=['resolve-idl']).install('gen')
goal(name='protoc', action=ProtobufGen,
  dependencies=['resolve-idl']).install('gen')
goal(name='antlr', action=AntlrGen,
  dependencies=['resolve-idl']).install('gen')

goal(
  name='checkstyle',
  action=Checkstyle,
  dependencies=['gen', 'resolve']
).install().with_description('Run checkstyle against java source code.')

def is_java(target):
  return (isinstance(target, JavaLibrary)
          or (isinstance(target, (JvmBinary, junit_tests, Benchmark))
              and has_sources(target, '.java')))

def is_scala(target):
  return (isinstance(target, (ScalaLibrary, ScalaTests, ScalacPlugin))
          or (isinstance(target, (JvmBinary, junit_tests, Benchmark))
              and has_sources(target, '.scala')))


goal(name='scala',
     action=ScalaCompile,
     group=group('jvm', is_scala),
     dependencies=['gen', 'resolve', 'check_exclusives']).install('compile').with_description(
       'Compile both generated and checked in code.'
     )
goal(name='apt',
     action=JavaCompile,
     group=group('jvm', is_apt),
     dependencies=['gen', 'resolve', 'check_exclusives']).install('compile')
goal(name='java',
     action=JavaCompile,
     group=group('jvm', is_java),
     dependencies=['gen', 'resolve', 'check_exclusives']).install('compile')

goal(name='prepare', action=PrepareResources).install('resources')

# TODO(John Sirois): pydoc also
goal(name='javadoc',
     action=JavadocGen,
     dependencies=['compile']).install('doc').with_description('Create documentation.')
goal(name='scaladoc',
     action=ScaladocGen,
     dependencies=['compile']).install('doc')


if MarkdownToHtml.AVAILABLE:
  goal(name='markdown',
       action=MarkdownToHtml
  ).install('markdown').with_description('Generate html from markdown docs.')


goal(name='jar',
     action=JarCreate,
     dependencies=['compile', 'resources']).install('jar').with_description('Create one or more jars.')


goal(name='junit',
     action=JUnitRun,
     dependencies=['compile', 'resources']).install('test').with_description('Test compiled code.')
goal(name='specs',
     action=SpecsRun,
     dependencies=['compile', 'resources']).install('test')

goal(name='bench',
     action=BenchmarkRun,
     dependencies=['compile', 'resources']).install('bench')

# TODO(John Sirois): Create pex's in binary phase
goal(
  name='binary',
  action=BinaryCreate,
  dependencies=['jar']
).install().with_description('Create a jvm binary jar.')
goal(
  name='bundle',
  action=BundleCreate,
  dependencies=['binary']
).install().with_description('Create an application bundle from binary targets.')

# run doesn't need the serialization lock. It's reasonable to run some code
# in a workspace while there's a compile going on unrelated code.
goal(
  name='jvm-run',
  action=JvmRun,
  dependencies=['compile', 'resources'],
  serialize=False,
).install('run').with_description('Run a (currently JVM only) binary target.')

goal(
  name='jvm-run-dirty',
  action=JvmRun,
  serialize=False,
).install('run-dirty').with_description('Run a (currently JVM only) binary target, using ' +
  'only currently existing binaries, skipping compilation')

# repl doesn't need the serialization lock. It's reasonable to have
# a repl running in a workspace while there's a compile going on unrelated code.
goal(
  name='scala-repl',
  action=ScalaRepl,
  dependencies=['compile', 'resources'],
  serialize=False,
).install('repl').with_description(
  'Run a (currently Scala only) REPL with the classpath set according to the targets.')

goal(
  name='scala-repl-dirty',
  action=ScalaRepl,
  serialize=False,
).install('repl-dirty').with_description(
  'Run a (currently Scala only) REPL with the classpath set according to the targets, ' +
  'using the currently existing binaries, skipping compilation')

goal(
  name='filedeps',
  action=FileDeps
).install('filedeps').with_description('Print out a list of all files the target depends on')

goal(
  name='pathdeps',
  action=PathDeps
).install('pathdeps').with_description(
  'Print out a list of all paths containing build files the target depends on')

goal(
  name='list',
  action=ListTargets
).install('list').with_description('List available BUILD targets.')

goal(
  name='buildlint',
  action=BuildLint,
  dependencies=['compile'],  # To pick up missing deps.
).install()


from twitter.pants.tasks.idea_gen import IdeaGen

goal(
  name='idea',
  action=IdeaGen,
  dependencies=['jar']
).install().with_description('Create an IntelliJ IDEA project from the given targets.')


from twitter.pants.tasks.eclipse_gen import EclipseGen

goal(
  name='eclipse',
  action=EclipseGen,
  dependencies=['jar']
).install().with_description('Create an Eclipse project from the given targets.')


from twitter.pants.tasks.provides import Provides

goal(
  name='provides',
  action=Provides,
  dependencies=['jar']
).install().with_description('Emit the list of symbols provided by the given targets.')


from twitter.pants.tasks.python.setup import SetupPythonEnvironment

goal(
  name='python-setup',
  action=SetupPythonEnvironment,
).install('setup').with_description(
"Setup the target's build environment.")

from twitter.pants.tasks.paths import Path, Paths

goal(
  name='path',
  action=Path,
).install().with_description('Find a dependency path from one target to another')

goal(
  name='paths',
  action=Paths,
).install().with_description('Find all dependency paths from one target to another')


from twitter.pants.tasks.dependees import ReverseDepmap

goal(
  name='dependees',
  action=ReverseDepmap
).install().with_description('Print a reverse dependency mapping for the given targets')


from twitter.pants.tasks.depmap import Depmap

goal(
  name='depmap',
  action=Depmap
).install().with_description('Generates either a textual dependency tree or a graphviz'
                             ' digraph dotfile for the dependency set of a target')


from twitter.pants.tasks.dependencies import Dependencies

goal(
  name='dependencies',
  action=Dependencies
).install().with_description('Extract textual infomation about the dependencies of a target')


from twitter.pants.tasks.filemap import Filemap

goal(
  name='filemap',
  action=Filemap
).install().with_description('Outputs a mapping from source file to'
                             ' the target that owns the source file')


from twitter.pants.tasks.minimal_cover import MinimalCover

goal(
  name='minimize',
  action=MinimalCover
).install().with_description('Print the minimal cover of the given targets.')


from twitter.pants.tasks.filter import Filter

goal(
  name='filter',
  action=Filter
).install().with_description('Filter the input targets based on various criteria.')
