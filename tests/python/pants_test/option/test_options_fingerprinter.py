# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import range, zip

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.option.custom_types import (UnsetBool, dict_option, dir_option, file_option, list_option,
                                       target_option)
from pants.option.options_fingerprinter import OptionsFingerprinter
from pants.util.contextutil import temporary_dir
from pants_test.test_base import TestBase


class OptionsFingerprinterTest(TestBase):

  def setUp(self):
    super(OptionsFingerprinterTest, self).setUp()
    self.options_fingerprinter = OptionsFingerprinter(self.context().build_graph)

  def test_fingerprint_dict(self):
    d1 = {'b': 1, 'a': 2}
    d2 = {'a': 2, 'b': 1}
    d3 = {'a': 1, 'b': 2}
    fp1, fp2, fp3 = (self.options_fingerprinter.fingerprint(dict_option, d)
                     for d in (d1, d2, d3))
    self.assertEquals(fp1, fp2)
    self.assertNotEquals(fp1, fp3)

  def test_fingerprint_list(self):
    l1 = [1, 2, 3]
    l2 = [1, 3, 2]
    fp1, fp2 = (self.options_fingerprinter.fingerprint(list_option, l)
                     for l in (l1, l2))
    self.assertNotEquals(fp1, fp2)

  def test_fingerprint_target_spec(self):
    specs = [':t1', ':t2']
    payloads = [Payload() for i in range(2)]
    for i, (s, p) in enumerate(zip(specs, payloads)):
      p.add_field('foo', PrimitiveField(i))
      self.make_target(s, payload=p)
    s1, s2 = specs

    fp_spec = lambda spec: self.options_fingerprinter.fingerprint(target_option, spec)
    fp1 = fp_spec(s1)
    fp2 = fp_spec(s2)
    self.assertNotEquals(fp1, fp2)

  def test_fingerprint_target_spec_list(self):
    specs = [':t1', ':t2', ':t3']
    payloads = [Payload() for i in range(3)]
    for i, (s, p) in enumerate(zip(specs, payloads)):
      p.add_field('foo', PrimitiveField(i))
      self.make_target(s, payload=p)
    s1, s2, s3 = specs

    fp_specs = lambda specs: self.options_fingerprinter.fingerprint(target_option, specs)
    fp1 = fp_specs([s1, s2])
    fp2 = fp_specs([s2, s1])
    fp3 = fp_specs([s1, s3])
    self.assertEquals(fp1, fp2)
    self.assertNotEquals(fp1, fp3)

  def test_fingerprint_file(self):
    fp1, fp2, fp3 = (self.options_fingerprinter.fingerprint(file_option,
                                                            self.create_file(f, contents=c))
                     for (f, c) in (('foo/bar.config', 'blah blah blah'),
                                    ('foo/bar.config', 'meow meow meow'),
                                    ('spam/egg.config', 'blah blah blah')))
    self.assertNotEquals(fp1, fp2)
    self.assertNotEquals(fp1, fp3)
    self.assertNotEquals(fp2, fp3)

  def test_fingerprint_file_outside_buildroot(self):
    with temporary_dir() as tmp:
      outside_buildroot = self.create_file(os.path.join(tmp, 'foobar'), contents='foobar')
      with self.assertRaises(ValueError):
        self.options_fingerprinter.fingerprint(file_option, outside_buildroot)

  def test_fingerprint_file_list(self):
    f1, f2, f3 = (self.create_file(f, contents=c) for (f, c) in
                  (('foo/bar.config', 'blah blah blah'),
                   ('foo/bar.config', 'meow meow meow'),
                   ('spam/egg.config', 'blah blah blah')))
    fp1 = self.options_fingerprinter.fingerprint(file_option, [f1, f2])
    fp2 = self.options_fingerprinter.fingerprint(file_option, [f2, f1])
    fp3 = self.options_fingerprinter.fingerprint(file_option, [f1, f3])
    self.assertEquals(fp1, fp2)
    self.assertNotEquals(fp1, fp3)

  def test_fingerprint_primitive(self):
    fp1, fp2 = (self.options_fingerprinter.fingerprint('', v) for v in ('foo', 5))
    self.assertNotEquals(fp1, fp2)

  def test_fingerprint_unset_bool(self):
    fp1 = self.options_fingerprinter.fingerprint(UnsetBool, UnsetBool)
    fp2 = self.options_fingerprinter.fingerprint(UnsetBool, UnsetBool)
    self.assertEqual(fp1, fp2)

  def test_fingerprint_dir(self):
    d1 = self.create_dir('a')
    d2 = self.create_dir('b')
    d3 = self.create_dir('c')

    f1, f2, f3, f4, f5 = (self.create_file(f, contents=c) for (f, c) in (
      ('a/bar/bar.config', 'blah blah blah'),
      ('a/foo/foo.config', 'meow meow meow'),
      ('b/foo/foo.config', 'meow meow meow'),
      ('b/bar/bar.config', 'blah blah blah'),
      ('c/bar/bar.config', 'blah meow blah')))
    dp1 = self.options_fingerprinter.fingerprint(dir_option, [d1])
    dp2 = self.options_fingerprinter.fingerprint(dir_option, [d1, d2])
    dp3 = self.options_fingerprinter.fingerprint(dir_option, [d2, d1])
    dp4 = self.options_fingerprinter.fingerprint(dir_option, [d3])

    self.assertEquals(dp1, dp1)
    self.assertEquals(dp2, dp2)
    self.assertNotEquals(dp1, dp3)
    self.assertNotEquals(dp1, dp4)
    self.assertNotEquals(dp2, dp3)
