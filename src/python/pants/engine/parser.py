# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod

from pants.engine.addressable import Exactly
from pants.util.meta import AbstractClass


class ParseError(Exception):
  """Indicates an error parsing BUILD configuration."""


class SymbolTable(AbstractClass):
  """A one-classmethod interface exposing a symbol table dict."""

  @abstractmethod
  def table(self):
    """Returns a dict of name to implementation class."""

  def constraint(self):
    """Returns the typeconstraint for the symbol table"""
    # NB Sort types so that multiple calls get the same tuples.
    symbol_table_types = sorted(set(self.table().values()))
    return Exactly(*symbol_table_types, description='symbol table types')


class EmptyTable(SymbolTable):
  def table(self):
    return {}


class Parser(AbstractClass):

  @abstractmethod
  def parse(self, filepath, filecontent):
    """
    :param string filepath: The name of the file being parsed. The parser should not assume
                            that the path is accessible, and should consume the filecontent.
    :param bytes filecontent: The raw byte content to parse.
    :returns: A list of decoded addressable, Serializable objects. The callable will
              raise :class:`ParseError` if there were any problems encountered parsing the filecontent.
    :rtype: :class:`collections.Callable`
    """
