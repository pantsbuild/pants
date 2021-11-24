# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Iterable, Optional

from pants.base.build_environment import pants_version
from pants.base.deprecated import warn_or_error
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Address
from pants.util.meta import classproperty


class PantsRequirementCAOF:
    """Exports a `python_requirement` pointing at the active Pants's corresponding dist.

    This requirement is useful for custom plugin authors who want to build and test their plugin with
    Pants itself. Using the resulting target as a dependency of their plugin target ensures the
    dependency stays true to the surrounding repo's version of Pants.

    NB: The requirement generated is for official Pants releases on PyPI; so may not be appropriate
    for use in a repo that tracks `pantsbuild/pants` or otherwise uses custom pants dists.

    :API: public
    """

    @classproperty
    def alias(self):
        return "pants_requirement"

    def __init__(self, parse_context):
        self._parse_context = parse_context

    def __call__(
        self,
        name: Optional[str] = None,
        dist: Optional[str] = None,
        *,
        modules: Optional[Iterable[str]] = None,
    ):
        """
        :param name: The name to use for the target, defaults to the dist name if specified and
            otherwise the parent dir name.
        :param dist: The Pants dist to create a requirement for. This must be a 'pantsbuild.pants*'
            distribution; eg: 'pantsbuild.pants.testutil'.
        :param modules: The modules exposed by the dist, e.g. `['pants.testutil']`. This defaults
            to the name of the dist without the leading `pantsbuild`.
        """
        warn_or_error(
            "2.10.0.dev0",
            "the `pants_requirement` macro",
            (
                "Use the target `pants_requirements` instead. First, add "
                "`pants.backend.plugin_development` to `[GLOBAL].backend_packages` in "
                "`pants.toml`. Then, delete all `pants_requirement` calls and replace them with "
                "a single `pants_requirements(name='pants')`.\n\n"
                "By default, `pants_requirements` will generate a `python_requirement` target for "
                "both `pantsbuild.pants` and `pantsbuild.pants.testutil`.\n\n"
                "The address for the generated targets will be different, e.g. "
                "`pants-plugins:pants#pantsbuild.pants` rather than "
                "`pants-plugins:pantsbuild.pants`. If you're using dependency inference, you "
                "should not need to update anything.\n\n"
                "The version of Pants is more useful now. If you're using a dev release, the "
                "version will be the exact release you're on, like before, to reduce the risk of "
                "a Plugin API change breaking your plugin. But if you're using a release candidate "
                "or stable release, the version will now be any non-dev release in the release "
                "series, e.g. any release candidate or stable release in Pants 2.9. This allows "
                "consumers of your plugin to use different patch versions than what you release "
                "the plugin with."
            ),
        )
        name = name or dist or os.path.basename(self._parse_context.rel_path)
        dist = dist or "pantsbuild.pants"
        if not (dist == "pantsbuild.pants" or dist.startswith("pantsbuild.pants.")):
            target = Address(spec_path=self._parse_context.rel_path, target_name=name)
            raise TargetDefinitionException(
                target=target,
                msg=(
                    f"The {self.alias} target only works for pantsbuild.pants distributions, but "
                    f"given {dist}"
                ),
            )

        if not modules:
            modules = [dist.replace("pantsbuild.", "")]
        self._parse_context.create_object(
            "python_requirement",
            name=name,
            requirements=[f"{dist}=={pants_version()}"],
            modules=modules,
        )
