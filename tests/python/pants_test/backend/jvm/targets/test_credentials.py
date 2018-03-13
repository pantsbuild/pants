# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.credentials import LiteralCredentials
from pants_test.base_test import BaseTest


class CredentialsTest(BaseTest):

  def test_literal_declaration(self):
    username = 'please don`t ever do this.'
    password = 'seriously, don`t.'
    t = self.make_target(':creds', LiteralCredentials, username=username, password=password)

    self.assertEquals(t.username('anything'), username)
    self.assertEquals(t.password('anything'), password)
