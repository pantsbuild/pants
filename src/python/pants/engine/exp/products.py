# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys

from pants.engine.exp.targets import Target
from pants.util.memo import memoized


class Products(object):
  @staticmethod
  def for_subject(subject):
    """Return the products that are concretely present for the given subject.

    TODO: these are synthetic products provided by LocalScheduler, but should
    likely become "real" products.
    """
    if isinstance(subject, Target):
      # Config products.
      for configuration in subject.configurations:
        yield type(configuration)
    else:
      # Any other type of subject is itself a product.
      yield type(subject)


def lift_native_product(subject, product_type):
  """Return's a subject's native products (as selected by Products.for_subject).

  TODO: This is a placeholder to demonstrate the concept of lifting products off of targets
  and into the product namespace.
  """
