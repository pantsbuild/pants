# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import closing

from twitter.common.lang import Compatibility


StringIO = Compatibility.StringIO


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
        yield ' %s' % chunk

  PATH = 'META-INF/MANIFEST.MF'

  MANIFEST_VERSION = 'Manifest-Version'
  CREATED_BY = 'Created-By'
  MAIN_CLASS = 'Main-Class'
  CLASS_PATH = 'Class-Path'

  def __init__(self, contents=''):
    self._contents = contents.strip().encode('ascii')

  def addentry(self, header, value):
    if len(header) > 68:
      raise ValueError('Header name must be 68 characters or less, given %s' % header)
    if self._contents:
      self._contents += '\n'
    self._contents += '\n'.join(self._wrap('%s: %s' % (header, value)))

  def contents(self):
    padded = self._contents + '\n'
    return padded.encode('ascii')
