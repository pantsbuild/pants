# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import re

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.build_graph.address import Address
from pants.build_graph.injectables_mixin import InjectablesMixin
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import target_option
from pants.subsystem.subsystem import Subsystem

logger = logging.getLogger(__name__)

SCOVERAGE = "scoverage"


class ScoveragePlatform(InjectablesMixin, Subsystem):
    """The scoverage platform."""

    options_scope = "scoverage"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--enable-scoverage",
            default=False,
            fingerprint=True,
            type=bool,
            help="Specifies whether to generate scoverage reports for scala test targets. "
            "Default value is False. If True, "
            "implies --test-junit-coverage-processor=scoverage.",
        )

        register(
            "--blacklist-targets",
            fingerprint=True,
            type=list,
            member_type=target_option,
            help="List of targets not to be instrumented. Accepts Regex patterns. All "
            "targets matching any of the patterns will not be instrumented. If no targets "
            "are specified, all targets will be instrumented.",
        )

    def scoverage_jar(self):
        return [
            JarDependency(
                org="com.twitter.scoverage",
                name="scalac-scoverage-plugin_2.12",
                rev="1.0.2-twitter",
            ),
            JarDependency(
                org="com.twitter.scoverage",
                name="scalac-scoverage-runtime_2.12",
                rev="1.0.2-twitter",
            ),
        ]

    def injectables(self, build_graph):
        specs_to_create = [
            ("scoverage", self.scoverage_jar),
        ]

        for spec_key, create_jardep_func in specs_to_create:
            address_spec = self.injectables_address_spec_for_key(spec_key)
            target_address = Address.parse(address_spec)
            if not build_graph.contains_address(target_address):
                target_jars = create_jardep_func()
                jars = target_jars if isinstance(target_jars, list) else [target_jars]
                build_graph.inject_synthetic_target(
                    target_address, JarLibrary, jars=jars, scope="forced"
                )
            elif not build_graph.get_target(target_address).is_synthetic:
                raise build_graph.ManualSyntheticTargetError(target_address)

    @property
    def injectables_address_spec_mapping(self):
        return {
            # Target spec for scoverage plugin.
            "scoverage": [f"//:scoverage"],
        }

    def is_blacklisted(self, target_address_spec) -> bool:
        """Checks if the [target] is blacklisted or not."""
        # No blacklisted targets specified.
        if not self.get_options().blacklist_targets:
            return False

        for filter in self.get_options().blacklist_targets:
            if re.search(filter, target_address_spec) is not None:
                logger.debug(f"{target_address_spec} found in blacklist, not instrumented.")
                return True
        return False
