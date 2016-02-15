# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class Spec(AbstractClass):
  """Represents address selectors as passed from the command line.
  
  Supports `Single` target addresses as well as `Sibling` (:) and `Descendant` (::) selector forms.

  Note: In general, 'spec' should not be a user visible term, it is usually appropriate to
  substitute 'address' for a spec resolved to an address, or 'address selector' if you are
  referring to an unresolved spec string.
  """
  pass


class SingleAddress(datatype('SingleAddress', ['directory', 'name']), Spec):
  """A Spec for a single address, with an optional name.

  If the address name is None, then the default address for the directory is assumed...
  ie, the address with the same name as the directory.
  """
  pass


class SiblingAddresses(datatype('SiblingAddresses', ['directory']), Spec):
  """A Spec representing all addresses located directly within the given directory."""
  pass


class DescendantAddresses(datatype('DescendantAddresses', ['directory']), Spec):
  """A Spec representing all addresses located recursively under the given directory."""
  pass
