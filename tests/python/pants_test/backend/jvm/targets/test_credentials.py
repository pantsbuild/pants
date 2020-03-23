# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.credentials import LiteralCredentials
from pants.testutil.test_base import TestBase


class CredentialsTest(TestBase):
    def test_literal_declaration(self):
        username = "please don`t ever do this."
        password = "seriously, don`t."
        t = self.make_target(":creds", LiteralCredentials, username=username, password=password)

        self.assertEqual(t.username("anything"), username)
        self.assertEqual(t.password("anything"), password)
