# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json

from pants.option.parser import Parser
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized

from pants.contrib.python.checks.checker.common import CheckstylePlugin


class PluginSubsystemBase(Subsystem):
    @classmethod
    def plugin_type(cls):
        """Returns the type of the plugin this subsystem configures."""
        raise NotImplementedError(
            "Subclasses must override and return the plugin type the subsystem " "configures."
        )

    _option_names = None

    @classmethod
    def register_options(cls, register):
        option_names = []

        def recording_register(*args, **kwargs):
            _, dest = Parser.parse_name_and_dest(*args, **kwargs)
            option_names.append(dest)
            register(*args, **kwargs)

        super().register_options(recording_register)

        # All checks have this option.
        recording_register("--skip", type=bool, help="If enabled, skip this style checker.")

        cls.register_plugin_options(recording_register)
        cls._option_names = frozenset(option_names)

    @classmethod
    def register_plugin_options(cls, register):
        """Register options for the corresponding plugin."""
        raise NotImplementedError("Subclasses must override instead of `register_options`.")

    def options_blob(self):
        assert (
            self._option_names is not None
        ), "Expected `register_options` to be called before any attempt to read the `options_blob`."
        options = self.get_options()
        options_dict = {
            option: options.get(option) for option in options if option in self._option_names
        }
        return json.dumps(options_dict) if options_dict else None


@memoized
def default_subsystem_for_plugin(plugin_type):
    """Create a singleton PluginSubsystemBase subclass for the given plugin type.

    The singleton enforcement is useful in cases where dependent Tasks are installed multiple times,
    to avoid creating duplicate types which would have option scope collisions.

    :param plugin_type: A CheckstylePlugin subclass.
    :type: :class:`pants.contrib.python.checks.checker.common.CheckstylePlugin`
    :rtype: :class:`pants.contrib.python.checks.tasks.checkstyle.plugin_subsystem_base.PluginSubsystemBase`
    """
    if not issubclass(plugin_type, CheckstylePlugin):
        raise ValueError(
            "Can only create a default plugin subsystem for subclasses of {}, given: {}".format(
                CheckstylePlugin, plugin_type
            )
        )

    return type(
        str("{}Subsystem".format(plugin_type.__name__)),
        (PluginSubsystemBase,),
        {
            str("options_scope"): "pycheck-{}".format(plugin_type.name()),
            str("plugin_type"): classmethod(lambda cls: plugin_type),
            str("register_plugin_options"): classmethod(lambda cls, register: None),
        },
    )
