# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from copy import copy

from pants.commands.command import Command


class Help(Command):
  """Provides help for available commands or a single specified command."""

  __command__ = 'help'

  def setup_parser(self, parser, args):
    self.parser = copy(parser)

    parser.set_usage("%prog help ([command])")
    parser.epilog = """Lists available commands with no arguments; otherwise prints help for the
                    specifed command."""

  def __init__(self, run_tracker, root_dir, parser, argv):
    Command.__init__(self, run_tracker, root_dir, parser, argv)

    if len(self.args) > 1:
      self.error("The help command accepts at most 1 argument.")
    self.subcommand = self.args[0]

  def execute(self):
    subcommand_class = Command.get_command(self.subcommand)
    if not subcommand_class:
      self.error("'%s' is not a recognized subcommand." % self.subcommand)
    command = subcommand_class(self.run_tracker, self.root_dir, self.parser, ['--help'])
    return command.execute()
