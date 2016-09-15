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
  """A one-classmethod interface exposing a symbol table dict.

  SymbolTables exist as named classes because it allows them to be loaded by name as a python
  module, rather than being pickled when they cross between processes.
  """

  @classmethod
  @abstractmethod
  def table(cls):
    """Returns a dict of name to implementation class."""

  @classmethod
  def constraint(cls):
    """Returns the typeconstraint for the symbol table"""
    # NB Sort types so that multiple calls get the same tuples.
    symbol_table_types = sorted(set(cls.table().values()))
    return Exactly(*symbol_table_types, description='symbol table types')


class Parser(AbstractClass):
  @classmethod
  @abstractmethod
  def parse(cls, filepath, filecontent, symbol_table_cls):
    """
    :param string filepath: The name of the file being parsed. The parser should not assume
                            that the path is accessible, and should consume the filecontent.
    :param bytes filecontent: The raw byte content to parse.
    :param dict symbol_table_cls: A symbol table to expose to the python file being parsed.
    :returns: A list of decoded addressable, Serializable objects. The callable will
              raise :class:`ParseError` if there were any problems encountered parsing the filecontent.
    :rtype: :class:`collections.Callable`
    """
