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
      target = subject
      # Source products.
      # TODO: after r/3274 it will no longer be necessary to iterate paths to determine the
      # type of Sources on a Target.
      source_extensions = set()
      for source in target.sources.iter_paths(base_path=target.address.spec_path):
        _, ext = os.path.splitext(source)
        if ext not in source_extensions:
          yield Sources.of(ext)
          source_extensions.add(ext)
      # Config products.
      for configuration in target.configurations:
        yield type(configuration)
    else:
      # Any other type of subject is itself a product.
      yield type(subject)


def lift_native_product(subject, product_type):
  """Return's a subject's native products (as selected by Products.for_subject).

  TODO: This is a placeholder to demonstrate the concept of lifting products off of targets
  and into the product namespace.
  """


class Sources(object):
  @classmethod
  @memoized
  def of(cls, ext):
    type_name = b'Sources({!r})'.format(ext)

    class_dict = {'ext': ext,
                  # We need custom serialization for the dynamic class type.
                  '__reduce__': lambda self: (_create_sources, ext)}

    ext_type = type(type_name, (cls,), class_dict)

    # Expose the custom class type at the module level to be pickle compatible.
    setattr(sys.modules[cls.__module__], type_name, ext_type)

    return ext_type

  @classmethod
  def ext(cls):
    raise NotImplementedError()

  def __repr__(self):
    return 'Sources(ext={!r})'.format(self.ext)
