# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_file import BuildFile
from pants.base.config import Config
from pants.base.workunit import WorkUnit


class Command(object):
  """Baseclass for all pants subcommands."""

  @staticmethod
  def get_command(name):
    return Command._commands.get(name, None)

  @staticmethod
  def all_commands():
    return Command._commands.keys()

  _commands = {}

  @classmethod
  def _register(cls):
    """Register a command class."""
    command_name = cls.__dict__.get('__command__', None)
    if command_name:
      Command._commands[command_name] = cls

  @classmethod
  def serialized(cls):
    return False

  def __init__(self,
               run_tracker,
               root_dir,
               parser,
               args,
               build_file_parser,
               build_graph):
    """run_tracker: The (already opened) RunTracker to track this run with
    root_dir: The root directory of the pants workspace
    parser: an OptionParser
    args: the subcommand arguments to parse"""
    self.run_tracker = run_tracker
    self.root_dir = root_dir
    self.build_file_parser = build_file_parser
    self.build_graph = build_graph

    config = Config.load()

    with self.run_tracker.new_workunit(name='bootstrap', labels=[WorkUnit.SETUP]):
      # construct base parameters to be filled in for BuildGraph
      for path in config.getlist('goals', 'bootstrap_buildfiles', default=[]):
        # try:
        build_file = BuildFile(root_dir=self.root_dir, relpath=path)
        self.build_file_parser.parse_build_file_family(build_file)
        # except (TypeError, ImportError):
        #   error(path, include_traceback=True)
        # except (IOError, SyntaxError):
        #   error(path)

    # Now that we've parsed the bootstrap BUILD files, and know about the SCM system.
    self.run_tracker.run_info.add_scm_info()

    # Override the OptionParser's error with more useful output
    def error(message=None, show_help=True):
      if message:
        print(message + '\n')
      if show_help:
        parser.print_help()
      parser.exit(status=1)
    parser.error = error
    self.error = error

    self.setup_parser(parser, args)
    self.options, self.args = parser.parse_args(args)
    self.parser = parser

  def setup_parser(self, parser, args):
    """Subclasses should override and confiure the OptionParser to reflect
    the subcommand option and argument requirements.  Upon successful
    construction, subcommands will be able to access self.options and
    self.args."""

    pass

  def error(self, message=None, show_help=True):
    """Reports the error message, optionally followed by pants help, and then exits."""

  def run(self, lock):
    """Subcommands that are serialized() should override if they need the ability to interact with
    the global command lock.
    The value returned should be an int, 0 indicating success and any other value indicating
    failure."""
    return self.execute()

  def execute(self):
    """Subcommands that do not require serialization should override to perform the command action.
    The value returned should be an int, 0 indicating success and any other value indicating
    failure."""
    raise NotImplementedError('Either run(lock) or execute() must be over-ridden.')

  def cleanup(self):
    """Called on SIGINT (e.g., when the user hits ctrl-c).
    Subcommands may override to perform cleanup before exit."""
    pass