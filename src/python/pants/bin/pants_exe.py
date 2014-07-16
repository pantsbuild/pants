# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging
import optparse
import os
import sys
import traceback

import psutil
from twitter.common.dirutil import Lock

from pants.base.build_environment import get_buildroot, pants_version
from pants.base.build_file_parser import BuildFileParser
from pants.base.build_graph import BuildGraph
from pants.base.config import Config
from pants.base.dev_backend_loader import load_build_configuration_from_source
from pants.base.rcfile import RcFile
from pants.base.workunit import WorkUnit
from pants.commands.command import Command
from pants.goal.initialize_reporting import initial_reporting
from pants.goal.run_tracker import RunTracker
from pants.reporting.report import Report
from pants.backend.jvm.tasks.nailgun_task import NailgunTask


_BUILD_COMMAND = 'build'
_LOG_EXIT_OPTION = '--log-exit'
_VERSION_OPTION = '--version'


def _do_exit(result=0, msg=None, out=sys.stderr):
  if msg:
    print(msg, file=out)
  if _LOG_EXIT_OPTION in sys.argv and result == 0:
    print("\nSUCCESS\n")
  sys.exit(result)


def _exit_and_fail(msg=None):
  _do_exit(result=1, msg=msg)


def _find_all_commands():
  for cmd in Command.all_commands():
    cls = Command.get_command(cmd)
    yield '%s\t%s' % (cmd, cls.__doc__)


def _add_default_options(command, args):
  expanded_options = RcFile(paths=['/etc/pantsrc', '~/.pants.rc']).apply_defaults([command], args)
  if expanded_options != args:
    print("(using ~/.pantsrc expansion: pants %s %s)" % (command, ' '.join(expanded_options)),
          file=sys.stderr)
  return expanded_options


def _synthesize_command(root_dir, args):
  command = args[0]

  if command in Command.all_commands():
    subcommand_args = args[1:] if len(args) > 1 else []
    return command, _add_default_options(command, subcommand_args)

  if command.startswith('-'):
    _exit_and_fail('Invalid command: %s' % command)

  # assume 'build' if a command was omitted.
  try:
    # Address.parse(root_dir, command)
    return _BUILD_COMMAND, _add_default_options(_BUILD_COMMAND, args)
  except:
    _exit_and_fail('Failed to execute pants build: %s' % traceback.format_exc())


def _parse_command(root_dir, args):
  command, args = _synthesize_command(root_dir, args)
  return Command.get_command(command), args


def _process_info(pid):
  process = psutil.Process(pid)
  return '%d (%s)' % (pid, ' '.join(process.cmdline))


def _run():
  """
  To add additional paths to sys.path, add a block to the config similar to the following:
  [main]
  roots: ['src/python/pants_internal/test/',]
  """

  logging.basicConfig()
  version = pants_version()
  if len(sys.argv) == 2 and sys.argv[1] == _VERSION_OPTION:
    _do_exit(msg=version, out=sys.stdout)

  root_dir = get_buildroot()
  if not os.path.exists(root_dir):
    _exit_and_fail('PANTS_BUILD_ROOT does not point to a valid path: %s' % root_dir)

  if len(sys.argv) < 2:
    argv = ['goal']
  else:
    argv = sys.argv[1:]
  # Hack to force ./pants -h etc. to redirect to goal.
  if argv[0] != 'goal' and set(['-h', '--help', 'help']).intersection(argv):
    argv = ['goal'] + argv

  parser = optparse.OptionParser(add_help_option=False, version=version)
  RcFile.install_disable_rc_option(parser)
  parser.add_option(_LOG_EXIT_OPTION,
                    action='store_true',
                    default=False,
                    dest='log_exit',
                    help='Log an exit message on success or failure.')

  config = Config.load()

  # XXX(wickman) This should be in the command goal, not in pants_exe.py!
  run_tracker = RunTracker.from_config(config)
  report = initial_reporting(config, run_tracker)
  run_tracker.start(report)

  url = run_tracker.run_info.get_info('report_url')
  if url:
    run_tracker.log(Report.INFO, 'See a report at: %s' % url)
  else:
    run_tracker.log(Report.INFO, '(To run a reporting server: ./pants goal server)')

  backend_packages = config.getlist('backends', 'packages')
  build_configuration = load_build_configuration_from_source(additional_backends=backend_packages)
  build_file_parser = BuildFileParser(build_configuration=build_configuration,
                                      root_dir=root_dir,
                                      run_tracker=run_tracker)
  build_graph = BuildGraph(run_tracker=run_tracker)

  command_class, command_args = _parse_command(root_dir, argv)
  command = command_class(run_tracker,
                          root_dir,
                          parser,
                          command_args,
                          build_file_parser,
                          build_graph)
  try:
    if command.serialized():
      def onwait(pid):
        process = psutil.Process(pid)
        print('Waiting on pants process %d (%s) to complete' %
              (pid, ' '.join(process.cmdline)), file=sys.stderr)
        return True
      runfile = os.path.join(root_dir, '.pants.run')
      lock = Lock.acquire(runfile, onwait=onwait)
    else:
      lock = Lock.unlocked()
    try:
      result = command.run(lock)
      if result:
        run_tracker.set_root_outcome(WorkUnit.FAILURE)
      _do_exit(result)
    except KeyboardInterrupt:
      command.cleanup()
      raise
    finally:
      lock.release()
  finally:
    run_tracker.end()
    # Must kill nailguns only after run_tracker.end() is called, because there may still
    # be pending background work that needs a nailgun.
    if (hasattr(command.options, 'cleanup_nailguns') and command.options.cleanup_nailguns) \
        or config.get('nailgun', 'autokill', default=False):
      NailgunTask.killall(None)

def main():
  try:
    _run()
  except KeyboardInterrupt:
    _exit_and_fail('Interrupted by user.')


if __name__ == '__main__':
  main()
