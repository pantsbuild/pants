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

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot, pants_version
from pants.base.build_file_address_mapper import BuildFileAddressMapper
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


_LOG_EXIT_OPTION = '--log-exit'
_VERSION_OPTION = '--version'
_PRINT_EXCEPTION_STACKTRACE = '--print-exception-stacktrace'


def _do_exit(result=0, msg=None, out=sys.stderr):
  if msg:
    print(msg, file=out)
  if _LOG_EXIT_OPTION in sys.argv and result == 0:
    print("\nSUCCESS\n")
  sys.exit(result)


def _exit_and_fail(msg=None):
  _do_exit(result=1, msg=msg)


def _unhandled_exception_hook(exception_class, exception, tb):
  msg = ''
  if _PRINT_EXCEPTION_STACKTRACE in sys.argv:
    msg = '\nException caught:\n' + ''.join(traceback.format_tb(tb))
  if str(exception):
    msg += '\nException message: %s\n' % str(exception)
  else:
    msg += '\nNo specific exception message.\n'
  # TODO(Jin Feng) Always output the unhandled exception details into a log file.
  _exit_and_fail(msg)


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

  _exit_and_fail('Pants build missing a command: args={args} tb=\n{tb}'
                 .format(args=args, tb=traceback.format_exc()))


def _parse_command(root_dir, args):
  command, args = _synthesize_command(root_dir, args)
  return Command.get_command(command), args

def _run():
  # Place the registration of the unhandled exception hook as early as possible in the code.
  sys.excepthook = _unhandled_exception_hook

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
  parser.add_option(_LOG_EXIT_OPTION,
                    action='store_true',
                    default=False,
                    dest='log_exit',
                    help='Log an exit message on success or failure.')

  config = Config.from_cache()

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
  address_mapper = BuildFileAddressMapper(build_file_parser)
  build_graph = BuildGraph(run_tracker=run_tracker, address_mapper=address_mapper)

  command_class, command_args = _parse_command(root_dir, argv)
  command = command_class(run_tracker,
                          root_dir,
                          parser,
                          command_args,
                          build_file_parser,
                          address_mapper,
                          build_graph)
  try:
    try:
      result = command.run()
      if result:
        run_tracker.set_root_outcome(WorkUnit.FAILURE)
      _do_exit(result)
    except KeyboardInterrupt:
      command.cleanup()
      raise
    except Exception:
      run_tracker.set_root_outcome(WorkUnit.FAILURE)
      raise
  finally:
    run_tracker.end()
    # Must kill nailguns only after run_tracker.end() is called, because there may still
    # be pending background work that needs a nailgun.
    # TODO(Eric Ayers) simplify after setup_py goes away.
    if (hasattr(command.old_options, 'cleanup_nailguns') and command.old_options.cleanup_nailguns) \
        or (hasattr(command, 'new_options')
            and command.new_options.for_global_scope().kill_nailguns) \
        or config.get('nailgun', 'autokill', default=False):
      NailgunTask.killall(None)

def main():
  try:
    _run()
  except KeyboardInterrupt:
    _exit_and_fail('Interrupted by user.')

if __name__ == '__main__':
  main()
