# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class PrepCommand(Target):
  """A command that must be run before some other target can be tested.

  For example, you can use `prep_command()` to execute a script that sets up tunnels to database
  servers. These tunnels could then be leveraged by integration tests.

  Pants will only execute the `prep_command()` under the test goal, when testing targets that
  depend on the `prep_command()` target.
  """

  def __init__(self, prep_executable=None, prep_args=None, payload=None, prep_environ=False, **kwargs):
    """
    :param prep_executable: The path to the executable that should be run.
    :param prep_args: A list of command-line args to the excutable.
    :param prep_environ: If True, the output of the command will be treated as
      a \\\\0-separated list of key=value pairs to insert into the environment.
      Note that this will pollute the environment for all future tests, so
      avoid it if at all possible.
    """
    payload = payload or Payload()
    payload.add_fields({
      'prep_command_executable': PrimitiveField(prep_executable),
      'prep_command_args': PrimitiveField(prep_args or []),
      'prep_environ': PrimitiveField(prep_environ),
    })
    super(PrepCommand, self).__init__(payload=payload, **kwargs)
