# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from collections import defaultdict
from textwrap import dedent


class ResourceMapping(object):
  RESOURCES_BY_CLASS_NAME_RE = re.compile(r'^(?P<classname>[\w+.\$]+) -> (?P<path>.+)$')

  class ResourceMappingFormatException(Exception):
    pass

  class MissingItemsLineException(ResourceMappingFormatException):
    pass

  class TooLongFileException(ResourceMappingFormatException):
    pass

  class TruncatedFileException(ResourceMappingFormatException):
    pass

  class UnparseableLineException(ResourceMappingFormatException):
    pass

  def __init__(self, classes_dir):
    self._classes_dir = classes_dir
    self._resource_mappings = None

  def _read_resource_mappings(self, mappings, lines):
    def parse_items(line):
      try:
        n, items = line.split(" ")
        return int(n)
      except ValueError as error:
        raise self.MissingItemsLineException(dedent('''
          Unable to parse resource mappings.
          Expected "N items", got "{line}: {error}"'''.format(line=line, error=error)))

    items_left = 0
    section = None
    for line in lines:
      line = line.strip()
      # Skip comments.
      if not line or line.startswith("#"):
        continue

      # We have just read a section name and now want to read a number of items
      if section:
        section = None
        items_left = parse_items(line)
        continue

      # This is the section we are looking for
      if line == "resources by class name:":
        section = line
        continue

      # Here, we read the individual items.
      if items_left:
        items_left -= 1
        match = ResourceMapping.RESOURCES_BY_CLASS_NAME_RE.match(line)
        if not match:
          raise self.UnparseableLineException(dedent('''
            Unable to parse resource mappings.
            Expected classname -> path, got "{line}"'''.format(line=line)))
        classname, path = match.group('classname'), match.group('path')
        mappings[classname].append(path)
      else:
        raise self.TooLongFileException('Unexpected line "{line}" in section {section}.'.format(
          line=line, section=section))

    if items_left:
      raise self.TruncatedFileException(dedent('''
        Unable to parse resource mappings.
        Found EOF while still missing {items_left} lines'''.format(items_left=items_left)))

  @property
  def mappings(self):
    """Returns a dict from class name to file name, from the resource-mappings in META-INF.

    The protocol is that annotation processors create files under
    META-INF/compiler/resource-mappings to describe any new files that
    they create and their relationship to class files.

    Each file contains some number of sections.  Each section starts
    with a section name followed by a colon and a newline.  The next
    line is an integer N followed by 'items' and a newline.  The next
    N lines contain [class name] ' -> ' [absolute output file path]

    Blank lines and lines with leading # (comment lines) are skipped.

    The section this method handles is "resources by class name".

    So far, this protocol is only implemented to by
    com.twitter.tools.args.apt.CmdLineProcessor from Twitter Commons;
    that's not enabled by default in pants.

    """
    if self._resource_mappings is not None:
      return self._resource_mappings

    mapping_dir = os.path.join(self._classes_dir, "META-INF", "compiler", "resource-mappings")
    mappings = defaultdict(list)
    if os.path.exists(mapping_dir):
      for filename in os.listdir(mapping_dir):
        path = os.path.join(mapping_dir, filename)
        with open(path) as f:
          self._read_resource_mappings(mappings, f.readlines())

    self._resource_mappings = mappings
    return self._resource_mappings

  def __getitem__(self, key):
    return self.mappings.get(key)

  def get(self, key, default=None):
    return self.mappings.get(key, default)

  def __str__(self):
    return "ResourceMapping({})".format(self.mappings)
