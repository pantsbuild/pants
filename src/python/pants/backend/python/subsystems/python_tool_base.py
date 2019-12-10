# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Optional, Sequence, Tuple

from pants.base.deprecated import deprecated_conditional
from pants.subsystem.subsystem import Subsystem


class PythonToolBase(Subsystem):
  """Base class for subsystems that configure a python tool to be invoked out-of-process."""

  # Subclasses must set.
  default_version: Optional[str] = None
  default_entry_point: Optional[str] = None
  # Subclasses used to need to set this, but it's now deprecated
  default_requirements: Optional[Sequence[str]] = None
  # Subclasses do not need to override.
  default_extra_requirements: Sequence[str] = []
  default_interpreter_constraints: Sequence[str] = []

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--version', type=str, advanced=True, fingerprint=True, default=cls.default_version,
             help="Requirement string for the tool.")
    register('--extra-requirements', type=list, member_type=str, advanced=True, fingerprint=True,
             default=cls.default_extra_requirements,
             help="Requirement string for the tool.")
    register('--interpreter-constraints', type=list, advanced=True, fingerprint=True,
             default=cls.default_interpreter_constraints,
             help='Python interpreter constraints for this tool. An empty list uses the default '
                  'interpreter constraints for the repo.')
    register('--requirements', type=list, advanced=True, fingerprint=True,
             default=cls.default_requirements,
             help='Python requirement strings for the tool.',
             removal_version='1.26.0.dev2',
             removal_hint="Instead of `--requirements`, use `--version` and, optionally, "
                          "`--extra-requirements`.")
    register('--entry-point', type=str, advanced=True, fingerprint=True,
             default=cls.default_entry_point,
             help='The main module for the tool.')

  def get_interpreter_constraints(self):
    return self.get_options().interpreter_constraints

  def get_requirement_specs(self) -> Tuple[str, ...]:
    deprecated_conditional(
      lambda: self.default_requirements is not None,
      removal_version="1.26.0.dev2",
      entity_description="Defining `default_requirements` for a subclass of `PythonToolBase`",
      hint_message="Instead of defining `default_requirements`, define `default_version` and, "
                   "optionally, `default_extra_requirements`."
    )

    opts = self.get_options()

    def configured_opts(*opt_names: str) -> List[str]:
      return [opt for opt in opt_names if not opts.is_default(opt)]

    def format_opts(opt_symbol_names: List[str]) -> str:
      cli_formatted = (f"--{opt.replace('_', '-')}" for opt in opt_symbol_names)
      return ', '.join(cli_formatted)

    configured_new_options = configured_opts('version', 'extra_requirements')
    configured_deprecated_options = configured_opts('requirements')

    if configured_new_options and configured_deprecated_options:
      raise ValueError(
        f"Conflicting options for requirements used. You provided these options in the new, "
        f"preferred style: `{format_opts(configured_new_options)}`, but also provided these options"
        f"in the deprecated style: `{format_opts(configured_deprecated_options)}`.\nPlease use "
        f"only one approach (preferably the new approach of `--version` and "
        f"`--extra-requirements`)."
      )
    if configured_deprecated_options:
      return tuple(opts.requirements)
    return (opts.version, *opts.extra_requirements)

  def get_entry_point(self):
    return self.get_options().entry_point
