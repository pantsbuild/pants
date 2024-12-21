# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging

from pants.core.util_rules.search_paths import ExecutableSearchPathsOptionMixin
from pants.engine.rules import collect_rules
from pants.option.option_types import BoolOption, StrListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class KubectlOptions(Subsystem):
    name = "kubectl"
    options_scope = "kubectl"
    help = "Kubernetes command line tool"

    class EnvironmentAware(ExecutableSearchPathsOptionMixin, Subsystem.EnvironmentAware):
        executable_search_paths_help = softwrap(
            """
            The PATH value that will be used to find kubectl binary.
            """
        )

    pass_context = BoolOption(
        default=True,
        help=softwrap(
            """
            Pass `--context` argument to `kubectl` command.
            """
        ),
    )
    extra_env_vars = StrListOption(
        help=softwrap(
            """
            Additional environment variables that would be made available to all Helm processes
            or during value interpolation.
            """
        ),
        default=["HOME", "KUBECONFIG", "KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT"],
        advanced=True,
    )


def rules():
    return collect_rules()
