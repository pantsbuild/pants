# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.optionable import Optionable
from pants.option.scope import ScopeInfo


class GoalOptionsRegistrar(Optionable):
  """Subclass this to register recursive options on all tasks in a goal."""
  options_scope_category = ScopeInfo.GOAL
