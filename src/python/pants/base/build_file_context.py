# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.goal import Context, Goal, Group, Phase
from pants.targets.pants_target import Pants
from pants.tasks import Task, TaskError


pants = Pants
goal = Goal
group = Group
phase = Phase

from .build_file_aliases import *
from .build_file_helpers import *
from .config import Config

# TODO(John Sirois): XXX kill
from .build_environment import *
