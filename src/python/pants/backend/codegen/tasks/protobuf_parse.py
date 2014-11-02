# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import re

DEFAULT_PACKAGE_PARSER = re.compile(r'^\s*package\s+([^;]+)\s*;\s*$')
OPTION_PARSER = re.compile(r'^\s*option\s+([^ =]+)\s*=\s*([^\s]+)\s*;\s*$')
SERVICE_PARSER = re.compile(r'^\s*(service)\s+([^\s{]+).*')
MESSAGE_PARSER = re.compile(r'^\s*(message)\s+([^\s{]+).*')
ENUM_PARSER = re.compile(r'^\s*(enum)\s+([^\s{]+).*')


class ProtobufParse():
  """ Parses a .proto file. """

  def __init__(self, path, source):
    """
    :param string path: base path to proto file
    :param string source: relative path to proto file with respect to the base
    """
    self.path = path
    self.source = source

    self.package = ''
    self.multiple_files = False
    self.services = set()
    self.outer_class_name = get_outer_class_name(source)

    # Note that nesting of types isn't taken into account
    self.enums = set()
    self.messages = set()

  def parse(self):
    lines = self._read_lines()
    type_depth = 0
    java_package = None

    for line in lines:
      match = DEFAULT_PACKAGE_PARSER.match(line)
      if match:
        self.package = match.group(1)
        continue
      else:
        match = OPTION_PARSER.match(line)
        if match:
          name = match.group(1)
          value = match.group(2).strip('"')
          if 'java_package' == name:
            java_package = value
          elif 'java_outer_classname' == name:
            self.outer_class_name = value
          elif 'java_multiple_files' == name:
            self.multiple_files = (value == 'true')
        else:
          uline = line.decode('utf-8').strip()
          type_depth += uline.count('{') - uline.count('}')
          match = SERVICE_PARSER.match(line)
          update_type_list(match, type_depth, self.services)
          if not match:
            match = ENUM_PARSER.match(line)
            if match:
              update_type_list(match, type_depth, self.enums)
              continue
            match = MESSAGE_PARSER.match(line)
            if match:
              update_type_list(match, type_depth, self.messages)
              continue

    if java_package:
      self.package = java_package

  def _read_lines(self):
    with open(self.path, 'r') as protobuf:
      lines = protobuf.readlines()
    return lines


def update_type_list(match, type_depth, outer_types):
  if match and type_depth < 2:  # This takes care of the case where { } are on the same line.
    type_name = match.group(2)
    outer_types.add(type_name)

def get_outer_class_name(source):
  filename = re.sub(r'\.proto$', '', os.path.basename(source))
  return camelcase(filename)

def camelcase(string):
  """Convert snake casing where present to camel casing"""
  return ''.join(word.capitalize() for word in re.split('[-_]', string))
