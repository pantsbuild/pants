# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str
from textwrap import dedent

# TODO: Create a dummy target type in this test and remove this dep.
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addressable import BuildFileAddresses
from pants.engine.legacy.graph import OwnersRequest
from pants_test.test_base import TestBase


class SourceMapperTest(TestBase):
  @classmethod
  def alias_groups(cls):
    return BuildFileAliases(
      targets={
        'java_library': JavaLibrary,
      },
    )

  def owner(self, owner, f):
    request = OwnersRequest(sources=(f,), include_dependees=str('none'))
    addresses, = self.scheduler.product_request(BuildFileAddresses, [request])
    self.assertEqual(set(owner), {i.spec for i in addresses})

  def test_target_address_for_source_yields_unique_addresses(self):
    # NB If the mapper returns more than one copy of an address, it may cause other code to do
    #    unnecessary work.
    self.add_to_build_file('path', dedent('''
    java_library(name='target',
                 sources=['BUILD'],
                 dependencies=[':buildholder']
    )
    java_library(name='buildholder',
                 sources=['BUILD']
    )
    '''))

    self.owner(['path:target', 'path:buildholder'], 'path/BUILD')

  def test_joint_ownership(self):
    # A simple target with two sources.
    self.create_library('lib/rpc', 'java_library', 'rpc', ['err.py', 'http.py'])
    # Another target with sources but also claims one already owned from above.
    self.create_library('lib', 'java_library', 'lib', ['a.py', 'b.py', 'rpc/net.py', 'rpc/err.py'])

    # Sole ownership of new files.
    self.owner(['lib:lib'], 'lib/a.py')
    self.owner(['lib:lib'], 'lib/rpc/net.py')
    self.owner(['lib/rpc:rpc'], 'lib/rpc/http.py')
    # Joint ownership of overlap file
    self.owner(['lib/rpc:rpc', 'lib:lib'], 'lib/rpc/err.py')

    # An unclaimed file in same dir is not claimed.
    self.create_file('lib/rpc/json.py')
    self.owner([], 'lib/rpc/json.py')

  def test_nested(self):
    # A root-level BUILD file's sources are found or not correctly.
    self.create_library('date', 'java_library', 'date', ['day.py', 'time/unit/hour.py'])
    self.create_file('date/time/unit/minute.py')
    # Shallow, simple source still works.
    self.owner(['date:date'], 'date/day.py')
    # Nested claimed source works.
    self.owner(['date:date'], 'date/time/unit/hour.py')
    # Unclaimed nested sibling correctly unclaimed.
    self.owner([], 'date/time/unit/minute.py')

  def test_with_root_level_build(self):
    self.create_library('', 'java_library', 'top', ['foo.py', 'text/common/const/emoji.py'])
    self.create_library('text', 'java_library', 'text', ['localize.py'])
    self.create_library('text/common/const', 'java_library', 'const', ['emoji.py', 'ascii.py'])
    self.create_library('text/common/helper', 'java_library', 'helper', ['trunc.py'])
    self.create_file('bar.py')

    self.owner(['text/common/helper:helper'], 'text/common/helper/trunc.py')
    self.owner(['//:top', 'text/common/const:const'], 'text/common/const/emoji.py')
    self.owner(['//:top'], 'foo.py')
    self.owner([], 'bar.py')
