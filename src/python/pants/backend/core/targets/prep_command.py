# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.base.target import Target


class PrepCommand(Target):
  """A command that must be run before some other target can be built.

  For example, a script that sets up tunnels to database servers
  might need to be run before running integration tests
  """

  def __init__(self, prep_executable=None, prep_args=None, payload=None, **kwargs):
    """
    :param executable: The path to the executable that should be run.
    """
    payload = payload or Payload()
    payload.add_fields({
      'prep_command_executable': PrimitiveField(prep_executable),
      'prep_command_args': PrimitiveField(prep_args or []),
    })
    super(PrepCommand, self).__init__(payload=payload, **kwargs)
