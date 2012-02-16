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

import inspect
import os
import sys
import time
import traceback

from contextlib import contextmanager
from copy import copy
from cStringIO import StringIO

from . import Command

from twitter.common import log
from twitter.common.dirutil import safe_mkdir, safe_rmtree

from twitter.pants import get_buildroot, goal, group, is_apt, is_scala
from twitter.pants.base import Address, BuildFile, ParseContext, Target
from twitter.pants.tasks import Context, Phase, Task
from twitter.pants.tasks.config import Config

class List(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("all"), dest="goal_list_all", default=False, action="store_true",
                            help="[%default] List all goals even if no description is available.")

  def execute(self, targets):
     print 'Installed goals:'
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
       print '  %s: %s' % (name.rjust(max_width), description)
     if undocumented:
       print '\nUndocumented goals:\n  %s' % ' '.join(undocumented)

goal(name='goals', action=List).install().with_description('List all documented goals.')


class Help(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    # Guard against double parsing for ./pants goal help help
    if not hasattr(cls, '_setup_parser'):
      cls._setup_parser = True

      def parser():
        parser = copy(option_group.parser)
        parser.option_groups.remove(option_group)
        return parser
      Help.parser = staticmethod(parser)

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

    parser = Help.parser()
    parser.set_usage('%s goal %s ([target]...)' % (sys.argv[0], goal))
    parser.epilog = phase.description
    Phase.setup_parser(parser, [], [phase])
    parser.parse_args(['--help'])

  def list_goals(self, message):
    print message
    print
    return Phase.execute(self.context, 'goals')

goal(name='help', action=Help).install().with_description('Provide help for the specified goal.')


class Goal(Command):
  """Lists installed goals or else executes a named goal."""

  __command__ = 'goal'

  @contextmanager
  def check_errors(self, banner):
    errors = {}
    def error(key, include_traceback=False):
      exc_type, exc_value, exc_traceback = sys.exc_info()
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
      self.error(msg.getvalue())

  def setup_parser(self, parser, args):
    self.config = Config.load()

    parser.add_option("-x", "--time", action="store_true", dest = "time", default = False,
                      help = "Times goal phases and outputs a report.")

    parser.add_option("-v", "--log", action="store_true", dest = "log", default = False,
                      help = "[%default] Logs extra build output.")
    parser.add_option("-l", "--level", dest = "log_level",
                      type="choice", choices=['debug', 'info', 'warn'],
                      help = "[info] Sets the logging level to one of 'debug', 'info' or 'warn', "
                             "implies -v if set.")

    parser.add_option("--all", dest="target_directory", action="append",
                      help = "Adds all targets found in the given directory's BUILD file.  Can "
                             "be specified more than once.")
    parser.add_option("--all-recursive", dest="recursive_directory", action="append",
                      help = "Adds all targets found recursively under the given directory.  Can "
                             "be specified more than once to add more than one root target "
                             "directory to scan.")

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
                       "attempts to achieve the specified goal for the listed targets.")

      parser.print_help()
      sys.exit(0)
    else:
      goals = []
      help = False
      multi = False
      for i, arg in enumerate(args):
        help = help or 'help' == arg
        goals.append(arg)
        if '--' == arg:
          multi = True
          del args[i]
          goals.pop()
          break
        if arg.startswith('-'):
          break
      if not multi:
        goals = [goals[0]]

      spec_offset = len(goals) + 1 if help else len(goals)
      specs = [arg for arg in args[spec_offset:] if not arg.startswith('-')]

      def parse_build(buildfile):
        # TODO(John Sirois): kill PANTS_NEW and its usages when pants.new is rolled out
        ParseContext(buildfile).parse(PANTS_NEW=True)

      # Bootstrap goals by loading any configured bootstrap BUILD files
      with self.check_errors('The following bootstrap_buildfiles cannot be loaded:') as error:
        for path in self.config.getlist('goals', 'bootstrap_buildfiles', default = []):
          try:
            buildfile = BuildFile(get_buildroot(), os.path.relpath(path, get_buildroot()))
            parse_build(buildfile)
          except (TypeError, ImportError):
            error(path, include_traceback=True)
          except (IOError, SyntaxError):
            error(path)

      # Bootstrap user goals by loading any BUILD files implied by targets
      self.targets = []
      with self.check_errors('The following targets could not be loaded:') as error:
        for spec in specs:
          try:
            address = Address.parse(get_buildroot(), spec)
            parse_build(address.buildfile)
            target = Target.get(address)
            if target:
              self.targets.append(target)
            else:
              siblings = Target.get_all_addresses(address.buildfile)
              prompt = 'did you mean' if len(siblings) == 1 else 'maybe you meant one of these'
              error('%s => %s?:\n    %s' % (address, prompt,
                                            '\n    '.join(str(a) for a in siblings)))
          except (TypeError, ImportError):
            error(spec, include_traceback=True)
          except (IOError, SyntaxError):
            error(spec)

      self.phases = [Phase(goal) for goal in goals]
      Phase.setup_parser(parser, args, self.phases)

  def execute(self):
    def add_targets(dir, buildfile):
      try:
        self.targets.extend(Target.get(addr) for addr in Target.get_all_addresses(buildfile))
      except (TypeError, ImportError):
        error(dir, include_traceback=True)
      except (IOError, SyntaxError):
        error(dir)

    if self.options.recursive_directory:
      with self.check_errors('There was a problem scanning the '
                             'following directories for targets:') as error:
        for dir in self.options.recursive_directory:
          for buildfile in BuildFile.scan_buildfiles(self.root_dir, dir):
            add_targets(dir, buildfile)

    if self.options.target_directory:
      with self.check_errors("There was a problem loading targets "
                             "from the following directory's BUILD files") as error:
        for dir in self.options.target_directory:
          add_targets(dir, BuildFile(self.root_dir, dir))

    timer = None
    if self.options.time:
      class Timer(object):
        def now(self):
          return time.time()
        def log(self, message):
          print message
      timer = Timer()

    logger = None
    if self.options.log or self.options.log_level:
      from twitter.common.log import init
      from twitter.common.log.options import LogOptions
      LogOptions.set_stdout_log_level((self.options.log_level or 'info').upper())
      logdir = self.config.get('goals', 'logdir')
      if logdir:
        safe_mkdir(logdir)
        LogOptions.set_log_dir(logdir)
      init('goals')
      logger = log

    context = Context(self.config, self.options, self.targets, log=logger)

    unknown = []
    for phase in self.phases:
      if not phase.goals():
        unknown.append(phase)

    if unknown:
        print 'Unknown goal(s): %s' % ' '.join(phase.name for phase in unknown)
        print
        return Phase.execute(context, 'goals')

    return Phase.attempt(context, self.phases, timer=timer)


# Install all default pants provided goals
from twitter.pants.targets import JavaLibrary, JavaTests
from twitter.pants.tasks.binary_create import BinaryCreate
from twitter.pants.tasks.bundle_create import BundleCreate
from twitter.pants.tasks.checkstyle import Checkstyle
from twitter.pants.tasks.ivy_resolve import IvyResolve
from twitter.pants.tasks.jar_create import JarCreate
from twitter.pants.tasks.jar_publish import JarPublish
from twitter.pants.tasks.java_compile import JavaCompile
from twitter.pants.tasks.javadoc_gen import JavadocGen
from twitter.pants.tasks.junit_run import JUnitRun
from twitter.pants.tasks.jvm_run import JvmRun
from twitter.pants.tasks.scala_repl import ScalaRepl
from twitter.pants.tasks.nailgun_task import NailgunTask
from twitter.pants.tasks.protobuf_gen import ProtobufGen
from twitter.pants.tasks.scala_compile import ScalaCompile
from twitter.pants.tasks.specs_run import SpecsRun
from twitter.pants.tasks.thrift_gen import ThriftGen


class Invalidator(Task):
  def execute(self, targets):
    self.invalidate(all=True)
goal(name='invalidate', action=Invalidator).install().with_description('Invalidate all caches')


class CleanAll(Task):
  def execute(self, targets):
    safe_rmtree(self.context.config.getdefault('pants_workdir'))
goal(
  name='clean-all',
  action=CleanAll,
  dependencies=['invalidate']
).install().with_description('Cleans all intermediate build output')


if NailgunTask.killall:
  class NailgunKillall(Task):
    @classmethod
    def setup_parser(cls, option_group, args, mkflag):
      option_group.add_option(mkflag("everywhere"), dest="ng_killall_evywhere",
                              default=False, action="store_true",
                              help="[%default] Kill all nailguns servers launched by pants for "
                                   "all workspaces on the system.")

    def execute(self, targets):
      if NailgunTask.killall:
        NailgunTask.killall(self.context.log, everywhere=self.context.options.ng_killall_evywhere)

  ng_killall = goal(name='ng-killall', action=NailgunKillall)
  ng_killall.install().with_description('Kill any running nailgun servers spawned by pants.')

  ng_killall.install('clean-all', first=True)


# TODO(John Sirois): Resolve eggs
goal(
  name='ivy',
  action=IvyResolve
).install('resolve').with_description('Resolves jar dependencies and produces dependency reports.')


# TODO(John Sirois): gen attempted as the sole Goal should gen for all known gen types but
# recognize flags to narrow the gen set
goal(name='thrift', action=ThriftGen).install('gen').with_description('Generate code.')
goal(name='protoc', action=ProtobufGen).install('gen')


checkstyle = goal(name='checkstyle',
                 action=Checkstyle,
                 dependencies=['gen', 'resolve'])


# Support straight up checkstyle runs in addition to checkstyle as last phase of compile below
goal(name='javac',
     action=JavaCompile,
     group=group('gen', lambda target: target.is_codegen),
     dependencies=['gen', 'resolve']).install('checkstyle')
checkstyle.install().with_description('Run checkstyle against java source code.')


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
checkstyle.install('compile')


# TODO(John Sirois): Create scaladoc and pydoc in a doc phase
goal(name='javadoc',
     action=JavadocGen,
     dependencies=['compile']).install('javadoc').with_description('Create javadoc.')
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

goal(
  name='jvm-run',
  action=JvmRun,
  dependencies=['resolve', 'compile']
).install('run').with_description('Run a (currently JVM only) binary target.')

goal(
  name='scala-repl',
  action=ScalaRepl,
  dependencies=['resolve', 'compile']
).install('repl').with_description('Run a (currently Scala only) REPL with the classpath set according to the targets.')
