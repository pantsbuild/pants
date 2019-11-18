# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List, Tuple

from pants.subsystem.subsystem import Subsystem


class PyTest(Subsystem):
  options_scope = 'pytest'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--version', default='pytest>=5.2.4', help="Requirement string for Pytest.")
    register(
      '--pytest-plugins',
      type=list,
      default=['pytest-timeout>=1.3.3', 'pytest-cov>=2.8.1'],
      help="Requirement strings for any plugins or additional requirements you'd like to use.",
    )
    register('--requirements', advanced=True, default='pytest>=5.2.4',
             help='Requirements string for the pytest library.',
             removal_version="1.25.0.dev0", removal_hint="Use --version instead.")
    register('--timeout-requirements', advanced=True, default='pytest-timeout>=1.3.3',
             help='Requirements string for the pytest-timeout library.',
             removal_version="1.25.0.dev0", removal_hint="Use --pytest-plugins instead.")
    register('--cov-requirements', advanced=True, default='pytest-cov>=2.8.1',
             help='Requirements string for the pytest-cov library.',
             removal_version="1.25.0.dev0", removal_hint="Use --pytest-plugins instead.")
    register('--unittest2-requirements', advanced=True,
             default="unittest2>=1.1.0 ; python_version<'3'",
             help='Requirements string for the unittest2 library, which some python versions '
                  'may need.',
             removal_version="1.25.0.dev0", removal_hint="Use --pytest-plugins instead.")

  def get_requirement_strings(self) -> Tuple[str, ...]:
    """Returns a tuple of requirements-style strings for Pytest and Pytest plugins."""
    opts = self.get_options()

    def configured_opts(*opt_names: str) -> List[str]:
      return [opt for opt in opt_names if not opts.is_default(opt)]

    def format_opts(opt_symbol_names: List[str]) -> str:
      cli_formatted = (f"--pytest-{opt.replace('_', '-')}" for opt in opt_symbol_names)
      return ', '.join(cli_formatted)

    configured_new_options = configured_opts("version", "pytest_plugins")
    configured_deprecated_option = configured_opts(
      "requirements", "timeout_requirements", "cov_requirements", "unittest2_requirements",
    )

    if configured_new_options and configured_deprecated_option:
      raise ValueError(
        "Conflicting options for --pytest used. You provided these options in the new, preferred "
        f"style: `{format_opts(configured_new_options)}`, but also provided these options in the "
        f"deprecated style: `{format_opts(configured_deprecated_option)}`.\nPlease use only one "
        f"approach (preferably the new approach of `--version` and `--pytest-plugins`)."
      )
    if configured_deprecated_option:
      return (
        opts.requirements,
        opts.timeout_requirements,
        opts.cov_requirements,
        opts.unittest2_requirements,
      )
    return (opts.version, *opts.pytest_plugins)
