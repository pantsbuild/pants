import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Optional

from pants.core.util_rules.search_paths import ExecutableSearchPathsOptionMixin
from pants.core.util_rules.system_binaries import BinaryPath, BinaryPathRequest, BinaryPaths
from pants.engine.fs import Digest
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, collect_rules, rule
from pants.option.option_types import BoolOption, ShellStrListOption, StrListOption
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class KubectlOptions(Subsystem):
    name = "kubectl"
    options_scope = "kubectl"
    help = "Kubernetes command line tool"

    available_contexts = StrListOption(
        default=[],
        help=softwrap(
            """
            List of available contexts for `kubectl` command.
            """
        ),
    )
    pass_context = BoolOption(
        default=True,
        help=softwrap(
            """
            Pass `--context` argument to `kubectl` command.
            """
        ),
    )

    class EnvironmentAware(ExecutableSearchPathsOptionMixin, Subsystem.EnvironmentAware):
        _env_vars = ShellStrListOption(
            help=softwrap(
                """
                Environment variables to set for `kubectl` invocations.

                Entries are either strings in the form `ENV_VAR=value` to set an explicit value;
                or just `ENV_VAR` to copy the value from Pants's own environment.
                """
            ),
            advanced=True,
        )
        executable_search_paths_help = softwrap(
            """
            The PATH value that will be used to find the kubectl binary.
            """
        )

        @property
        def env_vars(self) -> tuple[str, ...]:
            return tuple(sorted(set(self._env_vars)))


@dataclass(frozen=True)
class KubectlBinary(BinaryPath):
    """The `kubectl` binary."""

    def apply_configs(
        self,
        paths: Sequence[str],
        input_digest: Digest,
        env: Optional[Mapping[str, str]] = None,
        context: Optional[str] = None,
    ) -> Process:
        argv = (self.path,)

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


@rule(desc="Finding the `kubectl` binary", level=LogLevel.DEBUG)
async def get_kubectl(kubectl_options_env_aware: KubectlOptions.EnvironmentAware) -> KubectlBinary:
    search_path = kubectl_options_env_aware.executable_search_path
    request = BinaryPathRequest(
        binary_name="kubectl",
        search_path=search_path,
        # TODO test=BinaryPathTest(args=["version", "--output=json"]),
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    logger.debug("kubectl path %s", paths.first_path)
    first_path = paths.first_path_or_raise(request, rationale="interact with the kubernetes cluster")

    return KubectlBinary(first_path.path, first_path.fingerprint)


def rules():
    return collect_rules()
