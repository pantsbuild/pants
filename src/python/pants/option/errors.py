# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class OptionsError(Exception):
  """An options system-related error."""
  pass


class RegistrationError(OptionsError):
  """An error at option registration time."""
  pass


class ParseError(OptionsError):
  """An error at flag parsing time."""
  pass
