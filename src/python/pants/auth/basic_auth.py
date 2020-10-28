# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.subsystem import Subsystem


class BasicAuth(Subsystem):
    """Support for HTTP basicauth."""

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
            removal_version="2.1.0.dev0",
            removal_hint=(
                "The option `--basicauth-provides` does not do anything and the `[basicauth]` "
                "subsystem will be removed."
            ),
        )
        register(
            "--allow-insecure-urls",
            advanced=True,
            type=bool,
            default=False,
            help="Allow auth against non-HTTPS urls. Must only be set when testing!",
            removal_version="2.1.0.dev0",
            removal_hint=(
                "The option `--basicauth-allow-insecure-urls` does not do anything and the "
                "`[basicauth]` subsystem will be removed."
            ),
        )
