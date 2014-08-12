# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


class Mkflag(object):
  """A factory for namespaced flags."""

  def __init__(self, *namespace):
    """Creates a new Mkflag that will use the given namespace to prefix the flags it creates.

    namespace: a sequence of names forming the namespace
    """
    self._namespace = namespace

  @property
  def namespace(self):
    return list(self._namespace)

  def __call__(self, name, negate=False):
    """Creates a prefixed flag with an optional negated prefix.

    name: The simple flag name to be prefixed.
    negate: True to prefix the flag with '--no-'.
    """
    return '--{negate}{namespace}-{name}'.format(negate='no-' if negate else '',
                                                 namespace='-'.join(self._namespace),
                                                 name=name)

  def set_bool(self, option, opt_str, _, parser):
    """An Option callback to parse bool flags that recognizes the --no- negation prefix."""
    setattr(parser.values, option.dest, not opt_str.startswith("--no"))
