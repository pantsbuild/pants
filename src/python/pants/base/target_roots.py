# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.objects import datatype


class InvalidSpecConstraint(Exception):
  """Raised when invalid constraints are given via target specs and arguments like --changed*."""


class TargetRoots(object):
  """Determines the target roots for a given pants run."""


class ChangedTargetRoots(datatype('ChangedTargetRoots', ['addresses']), TargetRoots):
  """Target roots that have been altered by `--changed` functionality.

  Contains a list of `Address`es rather than `Spec`s, because all inputs have already been
  resolved, and are known to exist.
  """


class LiteralTargetRoots(datatype('LiteralTargetRoots', ['specs']), TargetRoots):
  """User defined target roots, as pants.base.specs.Spec objects."""
