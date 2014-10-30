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
TYPE_PARSER = re.compile(r'^\s*(enum|message)\s+([^\s{]+).*')


class ProtobufParse():
  """ Parses a .proto file. """

  def __init__(self, compiler, path, source):
    """
    :param string compiler: Name of the compiler that will compile proto files to Java files.
    :param string path: base path to proto file
    :param string source: relative path to proto file with respect to the base
    """
    self.compiler = compiler
    self.path = path
    self.source = source

    self.package = ''
    self.outer_class_name = get_outer_class_name(source)
    self.types = set()
    self.services = set()

  def parse(self):
    lines = self._read_lines()
    multiple_files = False
    outer_types = set()
    services = set()
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
            multiple_files = (value == 'true')
        else:
          uline = line.decode('utf-8').strip()
          type_depth += uline.count('{') - uline.count('}')
          match = SERVICE_PARSER.match(line)
          update_type_list(self.compiler, match, type_depth, services)
          if not match:
            match = TYPE_PARSER.match(line)
            update_type_list(self.compiler, match, type_depth, outer_types)

    # 'option java_package' supercedes 'package'
    if java_package:
      self.package = java_package

    if (self.compiler == 'protoc' and multiple_files and type_depth == 0):
      self.types = outer_types.union(services)
    elif self.compiler == 'wire':
      self.types = outer_types
      self.services = services

  def _read_lines(self):
    with open(self.path, 'r') as protobuf:
      lines = protobuf.readlines()
    return lines

def update_type_list(compiler, match, type_depth, outer_types):
  if match and type_depth < 2:  # This takes care of the case where { } are on the same line.
    type_name = match.group(2)
    outer_types.add(type_name)
    if match.group(1) == 'message' and compiler == 'protoc':
      outer_types.add('%sOrBuilder' % type_name)

def get_outer_class_name(source):
  filename = re.sub(r'\.proto$', '', os.path.basename(source))
  return camelcase(filename)

def camelcase(string):
  """Convert snake casing where present to camel casing"""
  return ''.join(word.capitalize() for word in re.split('[-_]', string))
