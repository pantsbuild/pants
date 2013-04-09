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

__author__ = 'jsirois'

import daemon
import inspect
import os
import sys
import time
import traceback

from contextlib import contextmanager
from optparse import Option, OptionParser

from twitter.common import log
from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir, safe_rmtree
from twitter.common.lang import Compatibility
from twitter.pants import get_buildroot, goal, group, is_apt, is_codegen, is_scala
from twitter.pants.base import Address, BuildFile, Config, ParseContext, Target, Timer
from twitter.pants.base.rcfile import RcFile
from twitter.pants.commands import Command
from twitter.pants.targets import InternalTarget
from twitter.pants.tasks import Task, TaskError
from twitter.pants.tasks.nailgun_task import NailgunTask
from twitter.pants.goal import Context, GoalError, Phase

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
    option_group.add_option(mkflag("goal"), dest = "help_goal", default=default)

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

class Goal(Command):
  """Lists installed goals or else executes a named goal."""

  __command__ = 'goal'

  GLOBAL_OPTIONS = [
    Option("-x", "--time", action="store_true", dest="time", default=False,
           help="Times goal phases and outputs a report."),
    Option("-k", "--kill-nailguns", action="store_true", dest="cleanup_nailguns", default=False,
           help="Kill nailguns before exiting"),
    Option("-v", "--log", action="store_true", dest="log", default=False,
           help="[%default] Logs extra build output."),
    Option("-d", "--logdir", dest="logdir",
           help="[%default] Forks logs to files under this directory."),
    Option("-l", "--level", dest="log_level", type="choice", choices=['debug', 'info', 'warn'],
           help="[info] Sets the logging level to one of 'debug', 'info' or 'warn', implies -v "
                  "if set."),
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

  # TODO(John Sirois): revisit wholesale locking when we move py support into pants new
  @classmethod
  def serialized(cls):
    # Goal serialization is now handled in goal execution during group processing.
    # The goal command doesn't need to hold the serialization lock; individual goals will
    # acquire the lock if they need to be serialized.
    return False

  def __init__(self, root_dir, parser, args):
    self.targets = []
    # Note that we can't gate this on the self.options.time flag, because self.options is
    # only set up in Command.__init__, and only after it calls setup_parser(), which uses the timer.
    self.timer = Timer()
    Command.__init__(self, root_dir, parser, args)

  @contextmanager
  def check_errors(self, banner):
    errors = {}
    def error(key, include_traceback=False):
      exc_type, exc_value, _ = sys.exc_info()
      msg = StringIO()
      if include_traceback:
        frame = inspect.trace()[-1]
        filename = frame[1]
        lineno = frame[2]
        funcname = frame[3]
        code = ''.join(frame[4])
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
      self.error(msg.getvalue(), show_help = False)

  def add_targets(self, error, dir, buildfile):
    try:
      self.targets.extend(Target.get(addr) for addr in Target.get_all_addresses(buildfile))
    except (TypeError, ImportError):
      error(dir, include_traceback=True)
    except (IOError, SyntaxError):
      error(dir)

  def get_dir(self, spec):
    path = spec.split(':', 1)[0]
    if os.path.isdir(path):
      return path
    else:
      if os.path.isfile(path):
        return os.path.dirname(path)
      else:
        return spec

  def add_target_recursive(self, *specs):
    with self.check_errors('There was a problem scanning the '
                           'following directories for targets:') as error:
      for spec in specs:
        dir = self.get_dir(spec)
        for buildfile in BuildFile.scan_buildfiles(self.root_dir, dir):
          self.add_targets(error, dir, buildfile)

  def add_target_directory(self, *specs):
    with self.check_errors("There was a problem loading targets "
                           "from the following directory's BUILD files") as error:
      for spec in specs:
        dir = self.get_dir(spec)
        try:
          self.add_targets(error, dir, BuildFile(self.root_dir, dir))
        except IOError:
          error(dir)

  def parse_spec(self, error, spec):
    if spec.endswith('::'):
      self.add_target_recursive(spec[:-len('::')])
    elif spec.endswith(':'):
      self.add_target_directory(spec[:-len(':')])
    else:
      try:
        address = Address.parse(get_buildroot(), spec)
        ParseContext(address.buildfile).parse()
        target = Target.get(address)
        if target:
          self.targets.append(target)
        else:
          siblings = Target.get_all_addresses(address.buildfile)
          prompt = 'did you mean' if len(siblings) == 1 else 'maybe you meant one of these'
          error('%s => %s?:\n    %s' % (address, prompt,
                                        '\n    '.join(str(a) for a in siblings)))
      except (TypeError, ImportError, TaskError, GoalError):
        error(spec, include_traceback=True)
      except (IOError, SyntaxError):
        error(spec)

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

      # TODO(John Sirois): kill PANTS_NEW and its usages when pants.new is rolled out
      ParseContext.enable_pantsnew()

      # Bootstrap goals by loading any configured bootstrap BUILD files
      with self.check_errors('The following bootstrap_buildfiles cannot be loaded:') as error:
        with self.timer.timing('parse:bootstrap'):
          for path in self.config.getlist('goals', 'bootstrap_buildfiles', default = []):
            try:
              buildfile = BuildFile(get_buildroot(), os.path.relpath(path, get_buildroot()))
              ParseContext(buildfile).parse()
            except (TypeError, ImportError, TaskError, GoalError):
              error(path, include_traceback=True)
            except (IOError, SyntaxError):
              error(path)

      # Bootstrap user goals by loading any BUILD files implied by targets
      with self.check_errors('The following targets could not be loaded:') as error:
        with self.timer.timing('parse:BUILD'):
          for spec in specs:
            self.parse_spec(error, spec)

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
          print("(using pantsrc expansion: pants goal %s)" % ' '.join(augmented_args))

      Phase.setup_parser(parser, args, self.phases)

  def run(self, lock):
    if self.options.dry_run:
      print '****** Dry Run ******'

    logger = None
    if self.options.log or self.options.log_level:
      from twitter.common.log import init
      from twitter.common.log.options import LogOptions
      LogOptions.set_stderr_log_level((self.options.log_level or 'info').upper())
      logdir = self.options.logdir or self.config.get('goals', 'logdir', default=None)
      if logdir:
        safe_mkdir(logdir)
        LogOptions.set_log_dir(logdir)
        init('goals')
      else:
        init()
      logger = log

    if self.options.recursive_directory:
      log.warn('--all-recursive is deprecated, use a target spec with the form [dir]:: instead')
      for dir in self.options.recursive_directory:
        self.add_target_recursive(dir)

    if self.options.target_directory:
      log.warn('--all is deprecated, use a target spec with the form [dir]: instead')
      for dir in self.options.target_directory:
        self.add_target_directory(dir)

    context = Context(
      self.config,
      self.options,
      self.targets,
      requested_goals=self.requested_goals,
      lock=lock,
      log=logger,
      timer=self.timer if self.options.time else None)

    unknown = []
    for phase in self.phases:
      if not phase.goals():
        unknown.append(phase)

    if unknown:
        print('Unknown goal(s): %s' % ' '.join(phase.name for phase in unknown))
        print('')
        return Phase.execute(context, 'goals')

    if logger:
      logger.debug('Operating on targets: %s', self.targets)

    ret = Phase.attempt(context, self.phases)

    if self.options.cleanup_nailguns or self.config.get('nailgun', 'autokill', default = False):
      if log:
        log.debug('auto-killing nailguns')
      if NailgunTask.killall:
        NailgunTask.killall(log)

    if self.options.time:
      print('Timing report')
      print('=============')
      self.timer.print_timings()

    return ret

  def cleanup(self):
    # TODO: Make this more selective? Only kill nailguns that affect state? E.g., checkstyle
    # may not need to be killed.
    if NailgunTask.killall:
      NailgunTask.killall(log)
    sys.exit(1)


# Install all default pants provided goals
from twitter.pants.targets import JavaLibrary, JavaTests
from twitter.pants.tasks.binary_create import BinaryCreate
from twitter.pants.tasks.build_lint import BuildLint
from twitter.pants.tasks.bundle_create import BundleCreate
from twitter.pants.tasks.checkstyle import Checkstyle
from twitter.pants.tasks.filedeps import FileDeps
from twitter.pants.tasks.ivy_resolve import IvyResolve
from twitter.pants.tasks.jar_create import JarCreate
from twitter.pants.tasks.jar_publish import JarPublish
from twitter.pants.tasks.java_compile import JavaCompile
from twitter.pants.tasks.javadoc_gen import JavadocGen
from twitter.pants.tasks.junit_run import JUnitRun
from twitter.pants.tasks.jvm_run import JvmRun
from twitter.pants.tasks.markdown_to_html import MarkdownToHtml
from twitter.pants.tasks.pathdeps import PathDeps
from twitter.pants.tasks.protobuf_gen import ProtobufGen
from twitter.pants.tasks.scala_compile import ScalaCompile
from twitter.pants.tasks.scala_repl import ScalaRepl
from twitter.pants.tasks.specs_run import SpecsRun
from twitter.pants.tasks.thrift_gen import ThriftGen


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

def async_safe_rmtree(root):
  new_path = root + '.deletable.%f' % time.time()
  if os.path.exists(root):
    os.rename(root, new_path)
    with daemon.DaemonContext():
      safe_rmtree(new_path)

goal(
  name='clean-all-async',
  action=lambda ctx: async_safe_rmtree(ctx.config.getdefault('pants_workdir')),
  dependencies=['invalidate']
).install().with_description('Cleans all intermediate build output in a background process')


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
    else:
      raise NotImplementedError, 'NailgunKillall not implemented on this platform'

ng_killall = goal(name='ng-killall', action=NailgunKillall)
ng_killall.install().with_description('Kill any running nailgun servers spawned by pants.')

ng_killall.install('clean-all', first=True)


# TODO(John Sirois): Resolve eggs
goal(
  name='ivy',
  action=IvyResolve,
  dependencies=['gen']
).install('resolve').with_description('Resolves jar dependencies and produces dependency reports.')


# TODO(John Sirois): gen attempted as the sole Goal should gen for all known gen types but
# recognize flags to narrow the gen set
goal(name='thrift', action=ThriftGen).install('gen').with_description('Generate code.')
goal(name='protoc', action=ProtobufGen).install('gen')


goal(
  name='checkstyle',
  action=Checkstyle,
  dependencies=['gen', 'resolve']
).install().with_description('Run checkstyle against java source code.')


# Support straight up checkstyle runs in addition to checkstyle as last phase of compile below
goal(name='javac',
     action=JavaCompile,
     group=group('gen', lambda target: is_codegen(target)),
     dependencies=['gen', 'resolve']).install('checkstyle')


def is_java(target):
 return isinstance(target, JavaLibrary) or \
        isinstance(target, JavaTests)

goal(name='scalac',
     action=ScalaCompile,
     group=group('jvm', is_scala),
     dependencies=['gen', 'resolve']).install('compile').with_description(
       'Compile both generated and checked in code.'
     )
goal(name='apt',
     action=JavaCompile,
     group=group('jvm', is_apt),
     dependencies=['gen', 'resolve']).install('compile')
goal(name='javac',
     action=JavaCompile,
     group=group('jvm', is_java),
     dependencies=['gen', 'resolve']).install('compile')


# TODO(John Sirois): Create scaladoc and pydoc in a doc phase
goal(name='javadoc',
     action=JavadocGen,
     dependencies=['compile']).install('javadoc').with_description('Create javadoc.')


if MarkdownToHtml.AVAILABLE:
  goal(name='markdown',
       action=MarkdownToHtml
  ).install('markdown').with_description('Generate html from markdown docs.')


goal(name='jar',
     action=JarCreate,
     dependencies=['compile']).install('jar').with_description('Create one or more jars.')

# TODO(John Sirois): Publish eggs in the publish phase
goal(name='publish',
     action=JarPublish,
     dependencies=[
       'javadoc',
       'jar'
     ]).install().with_description('Publish one or more artifacts.')

goal(name='junit',
     action=JUnitRun,
     dependencies=['compile']).install('test').with_description('Test compiled code.')
goal(name='specs',
     action=SpecsRun,
     dependencies=['compile']).install('test')

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
  dependencies=['compile'],
  serialize=False,
).install('run').with_description('Run a (currently JVM only) binary target.')

goal(
  name='jvm-run-dirty',
  action=JvmRun,
  serialize=False,
  ).install('run-dirty').with_description('Run a (currently JVM only) binary target, using\n' +
    'only currently existing binaries, skipping compilation')

# repl doesn't need the serialization lock. It's reasonable to have
# a repl running in a workspace while there's a compile going on unrelated code.
goal(
  name='scala-repl',
  action=ScalaRepl,
  dependencies=['compile'],
  serialize=False,
).install('repl').with_description(
  'Run a (currently Scala only) REPL with the classpath set according to the targets.')

goal(
  name='scala-repl-dirty',
  action=ScalaRepl,
  serialize=False,
).install('repl-dirty').with_description(
  'Run a (currently Scala only) REPL with the classpath set according to the targets, \n' +
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
