# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField


class JvmPrepCommand(JvmTarget):
  """A command (defined in a Java target) that must be run before other tasks in a goal.

  For example, you can use `jvm_prep_command()` to execute a script that sets up tunnels to database
  servers. These tunnels could then be leveraged by integration tests.

  You can define a jvm_prep_command() target as follows:

    jvm_prep_command(
      name='foo',
      goal='test',
      mainclass='com.example.myproject.BeforeTestMain',
      args=['--foo', 'bar'],
      jvm_options=['-Xmx256M', '-Dmy.property=baz'],
      dependencies=[
        'myproject/src/main/java:lib',
      ],
    )

  Pants will execute the `jvm_prep_command()` when processing the specified goal.  They will be
  triggered when running targets that depend on the `prep_command()` target or when the
  target is referenced from the command line.
  """

  @staticmethod
  def goals():
    return ['compile', 'test', 'binary']

  def __init__(self, payload=None, mainclass=None, args=None, jvm_options=None, goal=None,
      **kwargs):
    """
    :param args: A list of command-line args to the excutable.
    :param goal: Pants goal to run this command in [test, binary or compile]. If not specified,
                 runs in 'test'
    :param jvm_options: extra options to pass the JVM
    :param mainclass: The path to the executable that should be run.
    """
    payload = payload or Payload()
    goal = goal or 'test'
    payload.add_fields({
      'goal': PrimitiveField(goal),
      'mainclass': PrimitiveField(mainclass),
      'args': PrimitiveField(args or []),
      'jvm_options': PrimitiveField(jvm_options or []),
    })
    super(JvmPrepCommand, self).__init__(payload=payload, **kwargs)
    if not mainclass:
      raise TargetDefinitionException(self, 'mainclass must be specified')
    if goal not in self.goals():
      raise TargetDefinitionException(self, 'goal must be one of {}.'.format(self.goals()))
