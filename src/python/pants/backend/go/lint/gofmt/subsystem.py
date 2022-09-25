# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.option.subsystem import GoalToolMixin, Subsystem


class GofmtSubsystem(GoalToolMixin, Subsystem):
    options_scope = "gofmt"
    name = "gofmt"
    example_goal_name = "fmt"
    help = "Gofmt-specific options."
