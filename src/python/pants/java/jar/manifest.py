# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from contextlib import closing

from six import StringIO


class Manifest(object):
  """
    Implements the basics of the jar manifest specification.

    See: http://docs.oracle.com/javase/1.5.0/docs/guide/jar/jar.html#Manifest Specification
  """

  @staticmethod
  def _wrap(text):
    text = text.encode('ascii')
    with closing(StringIO(text)) as fp:
      yield fp.read(70)
      while True:
        chunk = fp.read(69)
        if not chunk:
          return
        yield ' {}'.format(chunk)

  PATH = 'META-INF/MANIFEST.MF'

  MANIFEST_VERSION = 'Manifest-Version'
  CREATED_BY = 'Created-By'
  MAIN_CLASS = 'Main-Class'
  CLASS_PATH = 'Class-Path'

  def __init__(self, contents=''):
    self._contents = contents.strip().encode('ascii')

  def addentry(self, header, value):
    if len(header) > 68:
      raise ValueError('Header name must be 68 characters or less, given {}'.format(header))
    if self._contents:
      self._contents += '\n'
    self._contents += '\n'.join(self._wrap('{header}: {value}'.format(header=header, value=value)))

  def contents(self):
    padded = self._contents + '\n'
    return padded.encode('ascii')

  def is_empty(self):
    if self._contents.strip():
      return False
    return True
