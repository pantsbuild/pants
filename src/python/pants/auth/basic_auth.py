# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import namedtuple
from dataclasses import dataclass
from typing import Dict, Optional

import requests
import www_authenticate

from pants.auth.cookies import Cookies
from pants.subsystem.subsystem import Subsystem
from pants.version import VERSION


@dataclass(frozen=True)
class Authentication:
    headers: Dict[str, str]
    request_args: Dict[str, str]


class BasicAuthException(Exception):
    pass


class BasicAuthAttemptFailed(BasicAuthException):
    def __init__(self, url, status_code, reason):
        msg = "Failed to auth against {}. Status code: {}. Reason: {}.".format(
            url, status_code, reason
        )
        super().__init__(msg)
        self.url = url


class Challenged(BasicAuthAttemptFailed):
    def __init__(self, url, status_code, reason, realm):
        super().__init__(url, status_code, reason)
        self.realm = realm


BasicAuthCreds = namedtuple("BasicAuthCreds", ["username", "password"])


class BasicAuth(Subsystem):
    options_scope = "basicauth"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--providers",
            type=dict,
            help="Map from provider name to config dict. This dict contains the following items: "
            "{provider_name: <url of endpoint that accepts basic auth and sets a session "
            "cookie>}. For example, `{'prod': 'https://app.pantsbuild.org/auth'}`.",
        )
        register(
            "--allow-insecure-urls",
            advanced=True,
            type=bool,
            default=False,
            help="Allow auth against non-HTTPS urls. Must only be set when testing!",
        )

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (Cookies,)

    def authenticate(
        self,
        provider: str,
        creds: Optional[BasicAuthCreds] = None,
        cookies: Optional[Cookies] = None,
    ) -> None:
        """Authenticate against the specified provider.

        :param provider: Authorize against this provider.
        :param creds: The creds to use. If unspecified, assumes that creds are set in the netrc file.
        :param cookies: Store the auth cookies in this instance. If unspecified, uses the global instance.
        :raises pants.auth.basic_auth.BasicAuthException: If auth fails due to misconfiguration or
          rejection by the server.
        """
        cookies = cookies or Cookies.global_instance()

        if not provider:
            raise BasicAuthException("No basic auth provider specified.")

        provider_config = self.get_options().providers.get(provider)
        if not provider_config:
            raise BasicAuthException(f"No config found for provider {provider}.")

        url = provider_config.get("url")
        if not url:
            raise BasicAuthException(f"No url found in config for provider {provider}.")
        if not self.get_options().allow_insecure_urls and not url.startswith("https://"):
            raise BasicAuthException(f"Auth url for provider {provider} is not secure: {url}.")

        auth = requests.auth.HTTPBasicAuth(creds.username, creds.password) if creds else None
        response = requests.get(url, auth=auth, headers={"User-Agent": f"pants/v{VERSION}"})

        if response.status_code != requests.codes.ok:
            if response.status_code == requests.codes.unauthorized:
                parsed = www_authenticate.parse(response.headers.get("WWW-Authenticate", ""))
                if "Basic" in parsed:
                    raise Challenged(
                        url, response.status_code, response.reason, parsed["Basic"]["realm"]
                    )
            raise BasicAuthException(url, response.status_code, response.reason)

        cookies.update(response.cookies)

    def get_auth_for_provider(self, auth_provider: Optional[str]) -> Authentication:
        cookies = Cookies.global_instance()
        return Authentication(headers={}, request_args={"cookies": cookies.get_cookie_jar()})
