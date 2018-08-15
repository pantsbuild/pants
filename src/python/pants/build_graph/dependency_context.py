# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import object

from pants.build_graph.aliased_target import AliasTarget
from pants.build_graph.target import Target


class DependencyContext(object):

  alias_types = (AliasTarget, Target)
  types_with_closure = ()
  target_closure_kwargs = {}
