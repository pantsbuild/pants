# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.option.subsystem import GoalToolMixin, Subsystem


class GoVetSubsystem(GoalToolMixin, Subsystem):
    options_scope = "go-vet"
    name = "`go vet`"
    example_goal_name = "lint"
    help = "`go vet`-specific options."
