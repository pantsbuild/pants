# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Optional

from pants.backend.k8s.kubectl_subsystem import KubectlOptions
from pants.core.util_rules.system_binaries import (
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
)
from pants.engine.fs import Digest
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


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
        argv: tuple[str, ...] = (self.path,)

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
        test=BinaryPathTest(args=["version", "--output=json", "--client=true"]),
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    logger.debug("kubectl path %s", paths.first_path)
    first_path = paths.first_path_or_raise(
        request, rationale="interact with the kubernetes cluster"
    )

    return KubectlBinary(first_path.path, first_path.fingerprint)


def rules():
    return collect_rules()
