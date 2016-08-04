# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.goal.task_registrar import TaskRegistrar as task

from example.pants_publish_plugin.extra_test_jar_example import ExtraTestJarExample


# Register this custom task on the 'jar' phase. When the RoundEngine reaches this phase, it will
# execute all tasks that have previously registered for this phase.
def register_goals():
  task(name='extra-test-jar-example', action=ExtraTestJarExample).install('jar')
