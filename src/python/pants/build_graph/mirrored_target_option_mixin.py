# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pants.util.memo import memoized_property


@dataclass(frozen=True)
class MirroredTargetOptionDeclaration:
    """An interface for operations to perform on an option which may also be set on a target."""

    options: Any
    option_name: str
    accessor: Any

    @memoized_property
    def is_flagged(self):
        """Whether the option was specified on the command line."""
        return self.options.is_flagged(self.option_name)

    def extract_target_value(self, target):
        """Get the value of this option from target.

        NB: If this method returns None, that is interpreted as the target not having a value set for
        the specified option, and the option value from `self.options` is used.
        """
        return self.accessor(target)

    @memoized_property
    def option_value(self):
        """Get the value of this option, separate from any target."""
        return self.options.get(self.option_name)

    # TODO(#7183): support list/set options in addition to scalars! We should apply the same
    # precedence order, but also provide some interface for allowing target fields to append or
    # remove an item from a set-valued option instead of completely overwriting it!
    def get_mirrored_scalar_option_value(self, target):
        # Options specified on the command line take precedence over anything else.
        if self.is_flagged:
            return self.option_value

        # Retrieve the value from the target, if set.
        target_setting = self.extract_target_value(target)
        if target_setting is not None:
            return target_setting

        # Otherwise, retrieve the value from the environment/pants.toml/hardcoded default.
        return self.option_value


class MirroredTargetOptionMixin(ABC):
    """Get option values which may be set in this subsystem or in a Target's keyword argument.

    A subsystem or task mixing in this class may set e.g.:

        mirrored_target_option_actions = {
          'some_option_name': lambda tgt: tgt.some_option_name,
        }

    which declares that '--some-option-name' can be set as a subsystem option which a target may
    override, and that the target needs to have a field `.some_option_name` which this subsystem may
    access.

    The class mixing this in can then call:

        some_option_value = self.get_scalar_mirrored_target_option('some_option_name', target)

    which will apply the following precedence to obtain `some_option_value`:
    1. If --some-option-name is "flagged" (provided on the command line), use the command-line value.
    2. If `target.some_option_name` is non-None, use that target-level value.
    3. Otherwise, return the option value from the environment, config, or hardcoded default.
    """

    @property
    @abstractmethod
    def mirrored_target_option_actions(self):
        """Subclasses should override and return a dict of (subsystem option name) -> selector
        function.

        A selector is a 1-argument function accepting a target and returning a value, or None. This
        property should return a dict mapping this subsystem's options attribute name (with
        underscores) to the corresponding selector.
        """

    @memoized_property
    def _mirrored_option_declarations(self):
        return {
            option_name: MirroredTargetOptionDeclaration(
                options=self.get_options(), option_name=option_name, accessor=accessor
            )
            for option_name, accessor in self.mirrored_target_option_actions.items()
        }

    def get_scalar_mirrored_target_option(self, option_name, target):
        """Get the attribute `field_name` from `target` if set, else from this subsystem's
        options."""
        mirrored_option_declaration = self._mirrored_option_declarations[option_name]
        return mirrored_option_declaration.get_mirrored_scalar_option_value(target)
