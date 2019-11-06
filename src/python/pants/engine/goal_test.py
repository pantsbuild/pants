# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.goal import Outputting
from pants_test.engine.util import MockConsole


def test_outputting_goal():
  class DummyGoal(Outputting):
    pass

  console = MockConsole()
  with DummyGoal.output(None, console) as output:
    pass
