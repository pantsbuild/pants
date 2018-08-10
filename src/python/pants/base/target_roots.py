# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.util.objects import datatype


class InvalidSpecConstraint(Exception):
  """Raised when invalid constraints are given via target specs and arguments like --changed*."""


class TargetRoots(datatype(['specs'])):
  """Determines the target roots for a given pants run."""
