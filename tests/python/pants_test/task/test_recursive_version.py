# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.task.recursive_version import RecursiveVersion


def test_missing_parent_version():
  class Foo(object):
    version = RecursiveVersion(1)


  class Bar(Foo):
    pass


  class Baz(Bar):
    version = RecursiveVersion(2)

  o = Baz()
  assert o.version == '1._.2'


def test_missing_tail():
  class Foo(object):
    version = RecursiveVersion(1)


  class Bar(Foo):
    version = RecursiveVersion(2)


  class Baz(Bar):
    pass

  o = Baz()
  assert o.version == '1.2._'


def test_full_version():
  class Foo(object):
    version = RecursiveVersion(1)


  class Bar(Foo):
    version = RecursiveVersion(2)


  class Baz(Bar):
    version = RecursiveVersion(3)

  o = Baz()
  assert o.version == '1.2.3'


def test_missing_base():
  class Foo(object):
    pass

  class Bar(Foo):
    version = RecursiveVersion(2)

  class Baz(Bar):
    version = RecursiveVersion(3)

  o = Baz()
  assert o.version == '_.2.3'


def test_toplevel_mixin():
  class Foo(object):
    pass

  class Bar(Foo):
    version = RecursiveVersion(2)

  class TopMixin(object):
    version = RecursiveVersion(20)

  class Baz(Bar, TopMixin):
    version = RecursiveVersion(3)

  o = Baz()
  assert o.version == '20._.2.3'


def test_inherited_mixin():
  class Foo(object):
    pass

  class MidMixin(object):
    version = RecursiveVersion(20)

  class Bar(Foo, MidMixin):
    version = RecursiveVersion(2)

  class Baz(Bar, ):
    version = RecursiveVersion(3)

  o = Baz()
  assert o.version == '20._.2.3'
