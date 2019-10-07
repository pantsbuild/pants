# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from http.cookiejar import LWPCookieJar

from pants.process.lock import OwnerPrintingInterProcessFileLock
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_mkdir_for
from pants.util.memo import memoized_property


class Cookies(Subsystem):
    options_scope = "cookies"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--path",
            advanced=True,
            fingerprint=True,
            default=os.path.join(register.bootstrap.pants_bootstrapdir, "auth", "cookies"),
            help="Path to file that stores persistent cookies. "
            "Defaults to <pants bootstrap dir>/auth/cookies.",
        )

    def update(self, cookies):
        """Add specified cookies to our cookie jar, and persists it.

        :param cookies: Any iterable that yields http.cookiejar.Cookie instances, such as a CookieJar.
        """
        cookie_jar = self.get_cookie_jar()
        for cookie in cookies:
            cookie_jar.set_cookie(cookie)
        with self._lock:
            cookie_jar.save()

    def get_cookie_jar(self):
        """Returns our cookie jar."""
        cookie_file = self._get_cookie_file()
        cookie_jar = LWPCookieJar(cookie_file)
        if os.path.exists(cookie_file):
            cookie_jar.load()
        else:
            safe_mkdir_for(cookie_file)
            # Save an empty cookie jar so we can change the file perms on it before writing data to it.
            with self._lock:
                cookie_jar.save()
            os.chmod(cookie_file, 0o600)
        return cookie_jar

    def _get_cookie_file(self):
        # We expanduser to make it easy for the user to config the cookies into their homedir.
        return os.path.realpath(os.path.expanduser(self.get_options().path))

    @memoized_property
    def _lock(self):
        """An identity-keyed inter-process lock around the cookie file."""
        lockfile = "{}.lock".format(self._get_cookie_file())
        safe_mkdir_for(lockfile)
        return OwnerPrintingInterProcessFileLock(lockfile)
