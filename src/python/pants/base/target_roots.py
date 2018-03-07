# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.objects import datatype


class InvalidSpecConstraint(Exception):
  """Raised when invalid constraints are given via target specs and arguments like --changed*."""


class TargetRoots(datatype('TargetRoots', ['specs', 'products', 'requires_legacy_graph'])):
  """Determines the target roots for a given pants run.

  :param specs: A list of `pants.base.spec.Spec` objects.
  :param products: A list of `pants.engine.selector.Selector` objects to be applied for the specs.
  :param requires_legacy_graph: True if a legacy `BuildGraph` instance is required to satisfy
    this TargetRoots request.
  """
