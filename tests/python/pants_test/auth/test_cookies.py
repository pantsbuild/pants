# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.auth.cookies import Cookies
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_dir


class TestCookies(TestBase):
    def test_cookie_file_permissions(self):
        with temporary_dir() as tmpcookiedir:
            cookie_file = os.path.join(tmpcookiedir, "pants.test.cookies")

            self.context(
                for_subsystems=[Cookies], options={Cookies.options_scope: {"path": cookie_file}}
            )

            cookies = Cookies.global_instance()
            self.assertFalse(os.path.exists(cookie_file))
            cookies.update([])
            self.assertTrue(os.path.exists(cookie_file))
            file_permissions = os.stat(cookie_file).st_mode
            self.assertEqual(int("0100600", 8), file_permissions)
