# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from collections.abc import Mapping, Sequence
from typing import Optional

from pants.core.util_rules.external_tool import TemplatedExternalTool
from pants.core.util_rules.search_paths import ExecutableSearchPathsOptionMixin
from pants.engine.internals.native_engine import Digest
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import collect_rules
from pants.option.option_types import BoolOption, StrListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class Kubectl(TemplatedExternalTool):
    name = "kubectl"
    options_scope = "kubectl"
    help = "Kubernetes command line tool"

    default_version = "1.32.0"
    default_known_versions = [
        "1.32.0|linux_arm64|d7389b9743b0b909c364d11bba94d13302171d751430b58c13dcdf248e924276|7605249",
        "1.32.0|linux_x86_64|d7389b9743b0b909c364d11bba94d13302171d751430b58c13dcdf248e924276|7605249",
        "1.32.0|macos_arm64|d7389b9743b0b909c364d11bba94d13302171d751430b58c13dcdf248e924276|7605249",
        "1.32.0|macos_x86_64|d7389b9743b0b909c364d11bba94d13302171d751430b58c13dcdf248e924276|7605249",
    ]
    version_constraints = ">=1,<2"

    default_url_template = "https://dl.k8s.io/release/{version}/bin/{platform}/kubectl"
    default_url_platform_mapping = {
        "linux_arm64": "linux/arm64",
        "linux_x86_64": "linux/amd64",
        "macos_arm64": "darwin/arm64",
        "macos_x86_64": "darwin/amd64",
    }

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
        default=[
            "HOME",
            "KUBECONFIG",
            "KUBERNETES_SERVICE_HOST",
            "KUBERNETES_SERVICE_PORT",
        ],
        advanced=True,
    )

    class EnvironmentAware(ExecutableSearchPathsOptionMixin, Subsystem.EnvironmentAware):
        executable_search_paths_help = softwrap(
            """
            The PATH value that will be used to find kubectl binary.
            """
        )

    def apply_configs(
        self,
        paths: Sequence[str],
        input_digest: Digest,
        platform: Platform,
        env: Optional[Mapping[str, str]] = None,
        context: Optional[str] = None,
    ) -> Process:
        argv: tuple[str, ...] = (self.generate_exe(platform),)

        if context is not None:
            argv += ("--context", context)

        argv += ("apply", "-o", "yaml")

        for path in paths:
            argv += ("-f", path)

        return Process(
            argv=argv,
            input_digest=input_digest,
            cache_scope=ProcessCacheScope.PER_SESSION,
            description=f"Applying kubernetes config {paths}",
            env=env,
        )


def rules():
    return collect_rules()
