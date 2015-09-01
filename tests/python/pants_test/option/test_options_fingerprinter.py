# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.option.custom_types import dict_option, file_option, list_option, target_list_option
from pants.option.options_fingerprinter import OptionsFingerprinter
from pants_test.base_test import BaseTest


class OptionsFingerprinterTest(BaseTest):

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

  def test_fingerprint_target_specs(self):
    specs = [':t1', ':t2', ':t3']
    payloads = [Payload() for i in range(3)]
    for i, (s, p) in enumerate(zip(specs, payloads)):
      p.add_field('foo', PrimitiveField(i))
      self.make_target(s, payload=p)
    s1, s2, s3 = specs

    fp_specs = lambda specs: self.options_fingerprinter.fingerprint(target_list_option, specs)
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

  def test_fingerprint_primitive(self):
    fp1, fp2 = (self.options_fingerprinter.fingerprint('', v) for v in ('foo', 5))
    self.assertNotEquals(fp1, fp2)
