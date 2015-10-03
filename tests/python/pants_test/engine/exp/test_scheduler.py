# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import os
import unittest

from pants.build_graph.address import Address
from pants.engine.exp.addressable import SubclassesOf, addressable_list
from pants.engine.exp.configuration import Configuration
from pants.engine.exp.graph import Graph
from pants.engine.exp.mapper import AddressMapper
from pants.engine.exp.parsers import encode_json, parse_json
from pants.engine.exp.targets import Target


class Jar(Configuration):
  """A pre-built Maven repository dependency."""

  def __init__(self, org, name, rev=None, **kwargs):
    """
    :param string org: The Maven ``groupId`` of this dependency.
    :param string name: The Maven ``artifactId`` of this dependency; also serves as the name portion
                        of the address of this jar if defined at the top level of a BUILD file.
    :param string rev: The Maven ``version`` of this dependency.
    """
    super(Jar, self).__init__(org=org, name=name, rev=rev, **kwargs)


class ApacheThriftConfiguration(Configuration):
  def __init__(self, rev, gen, strict=True, deps=None, **kwargs):
    """
    :param string rev: The version of the apache thrift compiler to use.
    :param string gen: The thrift compiler `--gen` argument specifying the type of code to generate
                       and any options to pass to the generator.
    :param bool strict: `False` to turn strict compiler warnings off (not recommended).
    :param deps: An optional list of dependencies needed by the generated code.
    :type deps: list of jars
    """
    super(ApacheThriftConfiguration, self).__init__(rev=rev, gen=gen, strict=strict, **kwargs)
    self.deps = deps

  # Could be Jars, PythonRequirements, ... we simply don't know a-priori - depends on --gen lang.
  @addressable_list(SubclassesOf(Configuration))
  def deps(self):
    """Return a list of the dependencies needed by the generated code."""


class SchedulerTest(unittest.TestCase):
  def setUp(self):
    build_root = os.path.join(os.path.dirname(__file__), 'examples', 'scheduler_inputs')
    symbol_table = {'jar': Jar,
                    'apache_thrift_configuration': ApacheThriftConfiguration,
                    'target': Target}
    json_parser = functools.partial(parse_json, symbol_table=symbol_table)
    self.graph = Graph(AddressMapper(build_root=build_root,
                                     build_pattern=r'^BLD.json$',
                                     parser=json_parser))

  def test_codegen_simple(self):
    # {
    #   "address": "src/java/codegen/simple",
    #   "dependencies": [
    #     {
    #       "address": "3rdparty/jvm:guava",
    #       "name": "guava",
    #       "org": "com.google.guava",
    #       "rev": "18.0",
    #       "type_alias": "jar"
    #     },
    #     {
    #       "address": "src/thrift/codegen/simple",
    #       "configurations": [
    #         {
    #           "deps": [
    #             {
    #               "name": "libthrift",
    #               "org": "org.apache.thrift",
    #               "rev": "0.9.2",
    #               "type_alias": "jar"
    #             },
    #             {
    #               "name": "commons-lang",
    #               "org": "commons-lang",
    #               "rev": "2.5",
    #               "type_alias": "jar"
    #             },
    #             {
    #               "name": "slf4j-api",
    #               "org": "org.slf4j",
    #               "rev": "1.6.1",
    #               "type_alias": "jar"
    #             }
    #           ],
    #           "gen": "java",
    #           "rev": "0.9.2",
    #           "strict": true,
    #           "type_alias": "apache_thrift_configuration"
    #         }
    #       ],
    #       "name": "simple",
    #       "sources": {
    #         "files": [
    #           "simple.thrift"
    #         ]
    #       },
    #       "type_alias": "pants.engine.exp.targets.Target"
    #     }
    #   ],
    #   "name": "simple",
    #   "sources": {
    #     "files": [
    #       "Java.java"
    #     ]
    #   },
    #   "type_alias": "target"
    # }
    simple_java = self.graph.resolve(Address.parse('src/java/codegen/simple'))
    print(encode_json(simple_java, inline=True, sort_keys=True, indent=2))
