# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from optparse import Option, OptionParser

import sys

from pants.base.config import Config


def _set_bool(option, opt_str, value, parser):
  setattr(parser.values, option.dest, not opt_str.startswith("--no"))


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
  Option("--no-colors", dest="no_color", action="store_true", default=False,
         help="Do not colorize log messages."),
  Option("-n", "--dry-run", action="store_true", dest="dry_run", default=False,
         help="Print the commands that would be run, without actually running them."),

  Option("--read-from-artifact-cache", "--no-read-from-artifact-cache", action="callback",
         callback=_set_bool, dest="read_from_artifact_cache", default=True,
         help="Whether to read artifacts from cache instead of building them, if configured to do so."),
  Option("--write-to-artifact-cache", "--no-write-to-artifact-cache", action="callback",
         callback=_set_bool, dest="write_to_artifact_cache", default=True,
         help="Whether to write artifacts to cache if configured to do so."),
]


def add_global_options(parser):
  for option in GLOBAL_OPTIONS:
    parser.add_option(option)


def setup_parser_for_phase_help(phase):
  """Returns an optparse.OptionParser useful for 'goal help <phase>'.
  Used by 'goal help' and 'goal builddict'.
  :param phase: Phase object
  """
  parser = OptionParser()
  parser.set_usage('%s goal %s ([target]...)' % (sys.argv[0], phase.name))
  parser.epilog = phase.description
  add_global_options(parser)
  phase.setup_parser(parser, [], [phase])
  return parser
