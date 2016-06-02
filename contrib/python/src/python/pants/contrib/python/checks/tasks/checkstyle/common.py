# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast
import codecs
import itertools
import os
import re
import textwrap
import tokenize
from abc import abstractmethod
from collections import Sequence

import six
from pants.util.meta import AbstractClass


__all__ = (
  'CheckstylePlugin',
  'PythonFile',
)


class OffByOneList(Sequence):

  def __init__(self, iterator):
    # Make sure we properly handle unicode chars in code files.
    self._list = list(iterator)

  def __iter__(self):
    return iter(self._list)

  def __reversed__(self):
    return reversed(self._list)

  def __len__(self):
    return len(self._list)

  def __getitem__(self, element_id):
    if isinstance(element_id, six.integer_types):
      return self.__get_list_item(element_id)
    elif isinstance(element_id, slice):
      return self.__getslice(element_id)
    raise TypeError('__getitem__ only supports integers and slices')

  def __getslice(self, sl):
    if sl.start == 0 or sl.stop == 0:
      raise IndexError
    new_slice = slice(sl.start - 1 if sl.start > 0 else sl.start,
                      sl.stop - 1 if sl.stop > 0 else sl.stop)
    return self._list[new_slice]

  def __get_list_item(self, item):
    if item == 0:
      raise IndexError
    if item < 0:
      return self._list[item]
    return self._list[item - 1]

  def index(self, value):
    return self._list.index(value) + 1


class PythonFile(object):
  """Checkstyle wrapper for Python source files."""
  SKIP_TOKENS = frozenset((tokenize.COMMENT, tokenize.NL, tokenize.DEDENT))

  @classmethod
  def _parse(cls, blob, filename):
    blob_minus_coding_header = cls._remove_coding_header(blob)
    try:
      tree = ast.parse(blob_minus_coding_header, filename)
    except SyntaxError as e:
      raise CheckSyntaxError(e, blob, filename)
    return tree

  @classmethod
  def _remove_coding_header(cls, blob):
    """
    There is a bug in ast.parse that cause it to throw a syntax error if
    you have a header similar to...
    # coding=utf-8,

    we replace this line with something else to bypass the bug.
    :param blob: file text contents
    :return: adjusted blob
    """
    # Remove the # coding=utf-8 to avoid AST erroneous parse errors
    #   https://bugs.python.org/issue22221
    lines = blob.split('\n')
    if lines and 'coding=utf-8' in lines[0]:
      lines[0] = '#remove coding'
    return '\n'.join(lines).encode('ascii', errors='replace')

  def __init__(self, blob, tree, filename):
    self._blob = self._remove_coding_header(blob)
    self.tree = tree
    self.lines = OffByOneList(self._blob.split('\n'))
    self.filename = filename
    self.logical_lines = dict((start, (start, stop, indent))
        for start, stop, indent in self.iter_logical_lines(self._blob))

  def __iter__(self):
    return iter(self.lines)

  def __getitem__(self, line_number):
    return self.lines[self.line_range(line_number)]

  def __str__(self):
    return 'PythonFile({filename})'.format(filename=self.filename)

  @classmethod
  def parse(cls, filename, root=None):
    """Parses the file at filename and returns a PythonFile.

    If root is specified, it will open the file with root prepended to the path. The idea is to
    allow for errors to contain a friendlier file path than the full absolute path.
    """
    if root is not None:
      if os.path.isabs(filename):
        raise ValueError("filename must be a relative path if root is specified")
      full_filename = os.path.join(root, filename)
    else:
      full_filename = filename

    with codecs.open(full_filename, encoding='utf-8') as fp:
      blob = fp.read()

    tree = cls._parse(blob, filename)

    return cls(blob, tree, filename)

  @classmethod
  def from_statement(cls, statement, filename='<expr>'):
    """A helper to construct a PythonFile from a triple-quoted string, for testing.
    :param statement: Python file contents
    :return: Instance of PythonFile
    """
    lines = textwrap.dedent(statement).split('\n')
    if lines and not lines[0]:  # Remove the initial empty line, which is an artifact of dedent.
      lines = lines[1:]

    blob = '\n'.join(lines)
    tree = cls._parse(blob, filename)
    return cls(blob, tree, filename)

  @classmethod
  def iter_tokens(cls, blob):
    """ Iterate over tokens found in blob contents
    :param blob: Input string with python file contents
    :return: token iterator
    """
    return tokenize.generate_tokens(six.StringIO(blob).readline)

  @property
  def tokens(self):
    """An iterator over tokens for this Python file from the tokenize module."""
    return self.iter_tokens(self._blob)

  @staticmethod
  def translate_logical_line(start, end, contents, indent_stack, endmarker=False):
    """Translate raw contents to logical lines"""
    # Remove leading blank lines.
    while contents[0] == '\n':
      start += 1
      contents.pop(0)
    # Remove trailing blank lines.
    while contents[-1] == '\n':
      end -= 1
      contents.pop()

    indent = len(indent_stack[-1]) if indent_stack else 0
    if endmarker:
      indent = len(contents[0])
    return start, end + 1, indent

  def iter_logical_lines(self, blob):
    """Returns an iterator of (start_line, stop_line, indent) for logical lines """
    indent_stack = []
    contents = []
    line_number_start = None
    for token in self.iter_tokens(blob):
      token_type, token_text, token_start = token[0:3]
      if token_type == tokenize.INDENT:
        indent_stack.append(token_text)
      if token_type == tokenize.DEDENT:
        indent_stack.pop()
      if token_type in self.SKIP_TOKENS:
        continue
      contents.append(token_text)
      if line_number_start is None:
        line_number_start = token_start[0]
      elif token_type in (tokenize.NEWLINE, tokenize.ENDMARKER):
        yield self.translate_logical_line(
            line_number_start,
            token_start[0] + (1 if token_type is tokenize.NEWLINE else -1),
            list(filter(None, contents)),
            indent_stack,
            endmarker=token_type == tokenize.ENDMARKER)
        contents = []
        line_number_start = None

  def line_range(self, line_number):
    """Return a slice for the given line number"""
    if line_number <= 0 or line_number > len(self.lines):
      raise IndexError('NOTE: Python file line numbers are offset by 1.')

    if line_number not in self.logical_lines:
      return slice(line_number, line_number + 1)
    else:
      start, stop, _ = self.logical_lines[line_number]
      return slice(start, stop)

  def enumerate(self):
    """Return an enumeration of line_number, line pairs."""
    return enumerate(self, 1)


class Nit(object):
  """Encapsulate a Style faux pas.

  The general taxonomy of nits:

  Prefix
    F => Flake8 errors
    E => PEP8 error
    W => PEP8 warning
    T => Twitter error

  Prefix:
    0 Naming
    1 Indentation
    2 Whitespace
    3 Blank line
    4 Import
    5 Line length
    6 Deprecation
    7 Statement
    8 Flake / Logic
    9 Runtime
  """

  COMMENT = 0
  WARNING = 1
  ERROR = 2

  SEVERITY = {
    COMMENT: 'COMMENT',
    WARNING: 'WARNING',
    ERROR: 'ERROR'
  }

  @staticmethod
  def flatten_lines(*line_or_line_list):
    return itertools.chain(*line_or_line_list)

  def __init__(self, code, severity, filename, message, line_range=None, lines=None):
    if severity not in self.SEVERITY:
      raise ValueError('Severity should be one of {}'.format(' '.join(self.SEVERITY.values())))
    if not re.match(r'[A-Z]\d{3}', code):
      raise ValueError('Code must contain a prefix letter followed by a 3 digit number')
    self.filename = filename
    self.code = code
    self.severity = severity
    self._message = message
    self._line_range = line_range
    self._lines = lines

  def __str__(self):
    """convert ascii for safe terminal output"""
    flat = list(self.flatten_lines([self.message], self.lines))
    return '\n     |'.join(flat).encode('ascii', errors='replace')

  @property
  def line_number(self):
    if self._line_range:
      line_range = self._line_range
      if line_range.stop - line_range.start > 1:
        return '%03d-%03d' % (line_range.start, line_range.stop - 1)
      else:
        return '%03d' % line_range.start

  @property
  def message(self):
    return '{code}:{severity:<7} {filename}:{linenum} {message}'.format(
        code=self.code,
        severity=self.SEVERITY[self.severity],
        filename=self.filename,
        linenum=self.line_number or '*',
        message=self._message)

  @property
  def lines(self):
    return self._lines or []

  @property
  def has_lines_to_display(self):
    return len(self.lines) > 0


class CheckSyntaxError(Exception):
  def __init__(self, syntax_error, blob, filename):
    self.filename = filename
    self._blob = blob
    self._syntax_error = syntax_error

  def as_nit(self):
    line_range = slice(self._syntax_error.lineno, self._syntax_error.lineno + 1)
    lines = OffByOneList(self._blob.split('\n'))
    # NB: E901 is the SyntaxError PEP8 code.
    # See:https://pep8.readthedocs.io/en/latest/intro.html#error-codes
    return Nit('E901', Nit.ERROR, self.filename,
               'SyntaxError: {error}'.format(error=self._syntax_error.msg),
               line_range=line_range, lines=lines)


class CheckstylePlugin(AbstractClass):
  """Interface for checkstyle plugins."""

  def __init__(self, options, python_file):
    super(CheckstylePlugin, self).__init__()
    if not isinstance(python_file, PythonFile):
      raise TypeError('CheckstylePlugin takes PythonFile objects.')
    self.options = options
    self.python_file = python_file

  def iter_ast_types(self, ast_type):
    for node in ast.walk(self.python_file.tree):
      if isinstance(node, ast_type):
        yield node

  @abstractmethod
  def nits(self):
    """Returns an iterable of Nit pertinent to the enclosed python file."""

  def __iter__(self):
    for nit in self.nits():
      yield nit

  def errors(self):
    for nit in self:
      if nit.severity is Nit.ERROR:
        yield nit

  def nit(self, code, severity, message, line_number_or_ast=None):
    line_number = None
    if isinstance(line_number_or_ast, six.integer_types):
      line_number = line_number_or_ast
    elif isinstance(line_number_or_ast, ast.AST):
      line_number = getattr(line_number_or_ast, 'lineno', None)

    if line_number:
      line_range = self.python_file.line_range(line_number)
      lines = self.python_file[line_number]
    else:
      line_range = None
      lines = None

    return Nit(code, severity, self.python_file.filename, message,
               line_range=line_range,
               lines=lines)

  def comment(self, code, message, line_number_or_ast=None):
    return self.nit(code, Nit.COMMENT, message, line_number_or_ast)

  def warning(self, code, message, line_number_or_ast=None):
    return self.nit(code, Nit.WARNING, message, line_number_or_ast)

  def error(self, code, message, line_number_or_ast=None):
    return self.nit(code, Nit.ERROR, message, line_number_or_ast)
