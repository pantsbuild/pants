# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import FrozenSet

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.runtime_platform_mixin import RuntimePlatformMixin
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField


class JvmPrepCommand(RuntimePlatformMixin, JvmTarget):
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

    See also prep_command for running shell commands.

    :API: public
    """

    _goals: FrozenSet[str] = frozenset()

    @staticmethod
    def add_goal(goal):
        """Add a named goal to the list of valid goals for the 'goal' parameter."""
        JvmPrepCommand._goals = frozenset(list(JvmPrepCommand._goals) + [goal])

    @classmethod
    def reset(cls) -> None:
        """Used for testing purposes to reset state."""
        cls._goals = frozenset()

    @staticmethod
    def goals() -> FrozenSet[str]:
        return JvmPrepCommand._goals

    def __init__(
        self,
        payload=None,
        mainclass=None,
        args=None,
        jvm_options=None,
        goal=None,
        runtime_platform=None,
        **kwargs
    ):
        """
        :param args: A list of command-line args to the excutable.
        :param goal: Pants goal to run this command in [test, binary or compile]. If not specified,
                     runs in 'test'
        :param jvm_options: extra options to pass the JVM
        :param mainclass: The path to the executable that should be run.
        :param str runtime_platform: The name of the platform (defined under the jvm-platform subsystem)
          to use for runtime (that is, a key into the --jvm-platform-platforms dictionary). If
          unspecified, the platform will default to the first one of these that exist: (1) the
          default_runtime_platform specified for jvm-platform, (2) the platform that would be used for
          the platform kwarg.
          """
        payload = payload or Payload()
        goal = goal or "test"
        payload.add_fields(
            {
                "goal": PrimitiveField(goal),
                "mainclass": PrimitiveField(mainclass),
                "args": PrimitiveField(args or []),
                "jvm_options": PrimitiveField(jvm_options or []),
            }
        )
        super().__init__(payload=payload, runtime_platform=runtime_platform, **kwargs)
        if not mainclass:
            raise TargetDefinitionException(self, "mainclass must be specified.")
        if goal not in self.goals():
            raise TargetDefinitionException(
                self, 'Got goal "{}". Goal must be one of {}.'.format(goal, self.goals())
            )
