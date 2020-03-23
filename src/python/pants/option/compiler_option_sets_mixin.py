# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.util.meta import classproperty

logger = logging.getLogger(__name__)


class CompilerOptionSetsMixin:
    """A mixin for language-scoped that support compiler option sets."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--compiler-option-sets-enabled-args",
            advanced=True,
            type=dict,
            fingerprint=True,
            default=cls.get_compiler_option_sets_enabled_default_value,
            help="Extra compiler args to use for each enabled option set.",
        )
        register(
            "--compiler-option-sets-disabled-args",
            advanced=True,
            type=dict,
            fingerprint=True,
            default=cls.get_compiler_option_sets_disabled_default_value,
            help="Extra compiler args to use for each disabled option set.",
        )
        register(
            "--default-compiler-option-sets",
            advanced=True,
            type=list,
            fingerprint=True,
            default=cls.get_default_compiler_option_sets,
            help="The compiler_option_sets to use for targets which don't declare any.",
        )

    @classproperty
    def get_compiler_option_sets_enabled_default_value(cls):
        """Override to set default for this option."""
        return {}

    @classproperty
    def get_compiler_option_sets_disabled_default_value(cls):
        """Override to set default for this option."""
        return {}

    @classproperty
    def get_default_compiler_option_sets(cls):
        """Override to set the default compiler_option_sets for targets which don't declare them."""
        return []

    @classproperty
    def get_fatal_warnings_enabled_args_default(cls):
        """Override to set default for this option."""
        return ()

    @classproperty
    def get_fatal_warnings_disabled_args_default(cls):
        """Override to set default for this option."""
        return ()

    # TODO(mateo): The compiler_option_sets could use an API that requires implementing platforms to
    # surface documentation - this took me awhile to unwind.
    def get_merged_args_for_compiler_option_sets(self, compiler_option_sets):
        # If no option sets are provided, use the default value.
        if not compiler_option_sets:
            compiler_option_sets = self.get_options().default_compiler_option_sets
            logger.debug(f"using default option sets: {compiler_option_sets}")

        compiler_options = []

        # Set values for disabled options (they will come before the enabled options). This allows
        # enabled option sets to override the disabled ones, if the underlying command has later
        # options supersede earlier options.
        compiler_options.extend(
            disabled_arg
            for option_set_key, disabled_args in self.get_options().compiler_option_sets_disabled_args.items()
            if option_set_key not in compiler_option_sets
            for disabled_arg in disabled_args
        )

        # Set values for enabled options.
        compiler_options.extend(
            enabled_arg
            for option_set_key in compiler_option_sets
            for enabled_arg in self.get_options().compiler_option_sets_enabled_args.get(
                option_set_key, []
            )
        )

        return compiler_options
