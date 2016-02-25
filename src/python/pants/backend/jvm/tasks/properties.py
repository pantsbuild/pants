# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
from collections import OrderedDict

import six


class Properties(object):
  """A Python reader for java.util.Properties formatted data.

  Based on:
  http://download.oracle.com/javase/6/docs/api/java/util/Properties.html#load(java.io.Reader)

  Originally copied from:
  https://github.com/twitter/commons/blob/master/src/python/twitter/common/config/properties.py

  :API: public
  """

  @staticmethod
  def load(data):
    """Loads properties from an open stream or the contents of a string.

    :API: public

    :param (string | open stream) data: An open stream or a string.
    :returns: A dict of parsed property data.
    :rtype: dict
    """

    if hasattr(data, 'read') and callable(data.read):
      contents = data.read()
    elif isinstance(data, six.string_types):
      contents = data
    else:
      raise TypeError('Can only process data from a string or a readable object, given: %s' % data)

    return Properties._parse(contents.splitlines())


  # An unescaped '=' or ':' forms an explicit separator
  _EXPLICIT_KV_SEP = re.compile(r'(?<!\\)[=:]')

  @staticmethod
  def _parse(lines):
    def coalesce_lines():
      line_iter = iter(lines)
      try:
        buffer = ''
        while True:
          line = next(line_iter)
          if line.strip().endswith('\\'):
            # Continuation.
            buffer += line.strip()[:-1]
          else:
            if buffer:
              # Continuation join, preserve left hand ws (could be a kv separator)
              buffer += line.rstrip()
            else:
              # Plain old line
              buffer = line.strip()

            try:
              yield buffer
            finally:
              buffer = ''
      except StopIteration:
        pass

    def normalize(atom):
      return re.sub(r'\\([:=\s])', r'\1', atom.strip())

    def parse_line(line):
      if line and not (line.startswith('#') or line.startswith('!')):
        match = Properties._EXPLICIT_KV_SEP.search(line)
        if match:
          return normalize(line[:match.start()]), normalize(line[match.end():])
        else:
          space_sep = line.find(' ')
          if space_sep == -1:
            return normalize(line), ''
          else:
            return normalize(line[:space_sep]), normalize(line[space_sep:])

    props = OrderedDict()
    for line in coalesce_lines():
      kv_pair = parse_line(line)
      if kv_pair:
        key, value = kv_pair
        props[key] = value
    return props

  @staticmethod
  def dump(props, output):
    """Dumps a dict of properties to the specified open stream or file path.

    :API: public
    """
    def escape(token):
      return re.sub(r'([=:\s])', r'\\\1', token)

    def write(out):
      for k, v in props.items():
        out.write('%s=%s\n' % (escape(str(k)), escape(str(v))))

    if hasattr(output, 'write') and callable(output.write):
      write(output)
    elif isinstance(output, six.string_types):
      with open(output, 'w+a') as out:
        write(out)
    else:
      raise TypeError('Can only dump data to a path or a writable object, given: %s' % output)
