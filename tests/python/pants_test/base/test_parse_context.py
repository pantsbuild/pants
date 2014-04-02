# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent

import pytest
from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_mkdir

from pants.base.address import Address
from pants.base.build_file import BuildFile
from pants.base.parse_context import ParseContext
from pants.base.target import Target
from pants_test.base_build_root_test import BaseBuildRootTest


def create_buildfile(root_dir, relpath, name='BUILD', content=''):
  path = os.path.join(root_dir, relpath)
  safe_mkdir(path)
  buildfile = os.path.join(path, name)
  with open(buildfile, 'a') as f:
    f.write(content)
  return BuildFile(root_dir, relpath)


class ParseContextTest(BaseBuildRootTest):
  def test_locate(self):
    with pytest.raises(ParseContext.ContextError):
      ParseContext.locate()

    with temporary_dir() as root_dir:
      a_context = ParseContext(create_buildfile(root_dir, 'a'))
      b_context = ParseContext(create_buildfile(root_dir, 'b'))

      def test_in_a():
        self.assertEquals(a_context, ParseContext.locate())
        return b_context.do_in_context(lambda: ParseContext.locate())

      self.assertEquals(b_context, a_context.do_in_context(test_in_a))

  def test_parse(self):
    with temporary_dir() as root_dir:
      buildfile = create_buildfile(root_dir, 'a',
        content=dedent("""
          with open('%s/a/b', 'w') as b:
            b.write('jack spratt')
        """ % root_dir).strip()
      )
      b_file = os.path.join(root_dir, 'a', 'b')
      self.assertFalse(os.path.exists(b_file))
      ParseContext(buildfile).parse()
      with open(b_file, 'r') as b:
        self.assertEquals('jack spratt', b.read())

  def test_on_context_exit(self):
    with temporary_dir() as root_dir:
      parse_context = ParseContext(create_buildfile(root_dir, 'a'))
      with pytest.raises(parse_context.ContextError):
        parse_context.on_context_exit(lambda: 37)

    with temporary_dir() as root_dir:
      buildfile = create_buildfile(root_dir, 'a',
        content=dedent("""
          import os
          from pants.base.parse_context import ParseContext
          def leave_a_trail(file, contents=''):
            with open(file, 'w') as b:
              b.write(contents)
          b_file = os.path.join(os.path.dirname(__file__), 'b')
          ParseContext.locate().on_context_exit(leave_a_trail, b_file, contents='42')
          assert not os.path.exists(b_file), 'Expected context exit action to be delayed.'
        """).strip()
      )
      b_file = os.path.join(root_dir, 'a', 'b')
      self.assertFalse(os.path.exists(b_file))
      ParseContext(buildfile).parse()
      with open(b_file, 'r') as b:
        self.assertEquals('42', b.read())

  def test_sibling_references(self):
    with temporary_dir() as root_dir:
      buildfile = create_buildfile(root_dir, 'a', name='BUILD',
        content=dedent("""
          dependencies(name='util',
            dependencies=[
              jar(org='com.twitter', name='util', rev='0.0.1')
            ]
          )
        """).strip()
      )
      sibling = create_buildfile(root_dir, 'a', name='BUILD.sibling',
        content=dedent("""
          dependencies(name='util-ex',
            dependencies=[
              pants(':util'),
              jar(org='com.twitter', name='util-ex', rev='0.0.1')
            ]
          )
        """).strip()
      )
      ParseContext(buildfile).parse()

      utilex = Target.get(Address.parse(root_dir, 'a:util-ex', is_relative=False))
      utilex_deps = set(utilex.resolve())

      util = Target.get(Address.parse(root_dir, 'a:util', is_relative=False))
      util_deps = set(util.resolve())

      self.assertEquals(util_deps, util_deps.intersection(utilex_deps))
