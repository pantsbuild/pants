# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty

from pants.util.meta import AbstractClass


class Lobs(AbstractClass):
  @abstractproperty
  def path_globs_kwarg(self):
    pass

  def __init__(self, *patterns, **kwargs):
    self.patterns = patterns
    if kwargs:
      raise ValueError('kwargs not supported for {}. Got: {}'.format(type(self), kwargs))


class Globs(Lobs):
  path_globs_kwarg = 'globs'


class RGlobs(Lobs):
  path_globs_kwarg = 'rglobs'


class ZGlobs(Lobs):
  path_globs_kwarg = 'zglobs'
