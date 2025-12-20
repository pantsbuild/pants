# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.metadata
import logging
import site
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from io import StringIO
from typing import cast

from packaging.requirements import Requirement

from pants.backend.python.subsystems.repos import PythonRepos
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest, VenvPexProcess, create_venv_pex
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.core.subsystems.uv import UvTool
from pants.core.subsystems.uv import rules as uv_rules
from pants.core.util_rules.adhoc_binaries import PythonBuildStandaloneBinary
from pants.core.util_rules.adhoc_binaries import rules as adhoc_binaries_rules
from pants.core.environments.rules import determine_bootstrap_environment
from pants.engine.collection import DeduplicatedCollection
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars, EnvironmentVarsRequest
from pants.engine.environment import EnvironmentName
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Params
from pants.engine.internals.session import SessionValues
from pants.engine.intrinsics import execute_process
from pants.engine.platform import Platform
from pants.engine.process import (
    Process,
    ProcessCacheScope,
    ProcessExecutionEnvironment,
    execute_process_or_raise,
)
from pants.engine.rules import QueryRule, collect_rules, implicitly, rule
from pants.init.bootstrap_scheduler import BootstrapScheduler
from pants.init.import_util import find_matching_distributions
from pants.option.global_options import GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginsRequest:
    # Interpreter constraints to resolve for, or None to resolve for the interpreter that Pants is
    # running under.
    interpreter_constraints: InterpreterConstraints | None
    # Requirement constraints to resolve with. If plugins will be loaded into the global working_set
    # (i.e., onto the `sys.path`), then these should be the current contents of the working_set.
    constraints: tuple[Requirement, ...]
    # Backend requirements to resolve
    requirements: tuple[str, ...]


class ResolvedPluginDistributions(DeduplicatedCollection[str]):
    sort_input = True


async def resolve_plugins_via_pex(
    request: PluginsRequest, global_options: GlobalOptions
) -> ResolvedPluginDistributions:
    """This rule resolves plugins using a VenvPex, and exposes the absolute paths of their dists.

    NB: This relies on the fact that PEX constructs venvs in a stable location (within the
    `named_caches` directory), but consequently needs to disable the process cache: see the
    ProcessCacheScope reference in the body.
    """
    logger.info("resolve_plugins_via_pex")

    req_strings = sorted(global_options.plugins + request.requirements)

    requirements = PexRequirements(
        req_strings_or_addrs=req_strings,
        constraints_strings=(str(constraint) for constraint in request.constraints),
        description_of_origin="configured Pants plugins",
    )
    if not requirements:
        return ResolvedPluginDistributions()

    python: PythonExecutable | None = None
    if not request.interpreter_constraints:
        python = PythonExecutable.fingerprinted(
            sys.executable, ".".join(map(str, sys.version_info[:3])).encode("utf8")
        )

    plugins_pex = await create_venv_pex(
        **implicitly(
            PexRequest(
                output_filename="pants_plugins.pex",
                internal_only=True,
                python=python,
                requirements=requirements,
                interpreter_constraints=request.interpreter_constraints or InterpreterConstraints(),
                description=f"Resolving plugins: {', '.join(req_strings)}",
            )
        )
    )

    # NB: We run this Process per-restart because it (intentionally) leaks named cache
    # paths in a way that invalidates the Process-cache. See the method doc.
    cache_scope = (
        ProcessCacheScope.PER_SESSION
        if global_options.plugins_force_resolve
        else ProcessCacheScope.PER_RESTART_SUCCESSFUL
    )

    plugins_process_result = await execute_process_or_raise(
        **implicitly(
            VenvPexProcess(
                plugins_pex,
                argv=("-c", "import os, site; print(os.linesep.join(site.getsitepackages()))"),
                description="Extracting plugin locations",
                level=LogLevel.DEBUG,
                cache_scope=cache_scope,
            )
        )
    )
    return ResolvedPluginDistributions(plugins_process_result.stdout.decode().strip().split("\n"))


@dataclass(frozen=True)
class _UvPluginResolveScript:
    digest: Digest
    path: str


# Script which invokes `uv` to resolve plugin distributions. It builds a mini-uv project in a subdirectory
# of the repository and uses `uv` to manage the venv in that project.
_UV_PLUGIN_RESOLVE_SCRIPT = r"""\
import os
from pathlib import Path
import shutil
from subprocess import run
import sys


def pyproject_changed(current_path: Path, previous_path: Path) -> bool:
    with open(current_path, "rb") as f:
        current_pyproject = f.read()

    with open(previous_path, "rb") as f:
        previous_pyproject = f.read()

    return current_pyproject != previous_pyproject


inputs_dir = Path(sys.argv[1])
uv_path = inputs_dir / sys.argv[2]
pyproject_path = inputs_dir / sys.argv[3]

plugins_path = Path(".pants.d/plugins")
plugins_path.mkdir(parents=True, exist_ok=True)
os.chdir(plugins_path)

shutil.copy(pyproject_path, ".")

run([uv_path, "sync", f"--python={sys.executable}"], check=True)
run(["./.venv/bin/python", "-c", "import os, site; print(os.linesep.join(site.getsitepackages()))"], check=True)
"""


@rule
async def _setup_uv_plugin_resolve_script() -> _UvPluginResolveScript:
    digest = await Get(
        Digest,
        CreateDigest(
            [FileContent(content=_UV_PLUGIN_RESOLVE_SCRIPT.encode(), path="uv_plugin_resolve.py")]
        ),
    )
    return _UvPluginResolveScript(digest=digest, path="uv_plugin_resolve.py")


_PYPROJECT_TEMPLATE = """\
[project]
name = "pants-plugins"
version = "0.0.1"
description = "Plugins for your Pants"
requires-python = "==3.11.*"
dependencies = [{requirements_formatted}]
[tool.uv]
package = false
fork-strategy = "requires-python"
environments = ["sys_platform == '{platform}'"]
constraint-dependencies = [{constraints_formatted}]
find-links = [{find_links_formatted}]
{indexes_formatted}
[tool.__pants_internal__]
version = {version}
"""


def _generate_pyproject_toml(
    requirements: Iterable[str],
    constraints: Iterable[str],
    python_indexes: Sequence[str],
    python_find_links: Iterable[str],
) -> str:
    requirements_formatted = ", ".join([f'"{x}"' for x in requirements])
    constraints_formatted = ", ".join([f'"{x}"' for x in constraints])
    find_links_formatted = ", ".join([f'"{x}"' for x in python_find_links])

    indexes_formatted = StringIO()
    if python_indexes:
        for python_index in python_indexes:
            indexes_formatted.write(f"""[[tool.uv.index]]\nurl = "{python_index}"\n""")
        indexes_formatted.write("default = true")
    else:
        indexes_formatted.write("no-index = true")

    return _PYPROJECT_TEMPLATE.format(
        constraints_formatted=constraints_formatted,
        find_links_formatted=find_links_formatted,
        indexes_formatted=indexes_formatted.getvalue(),
        platform=sys.platform,
        requirements_formatted=requirements_formatted,
        version=0,
    )


async def resolve_plugins_via_uv(
    request: PluginsRequest, global_options: GlobalOptions
) -> ResolvedPluginDistributions:
    req_strings = sorted(global_options.plugins + request.requirements)
    if not req_strings:
        return ResolvedPluginDistributions()

    python_repos = await Get(PythonRepos)

    pyproject_content = _generate_pyproject_toml(
        requirements=req_strings,
        constraints=(str(c) for c in request.constraints),
        python_indexes=python_repos.indexes,
        python_find_links=python_repos.find_links,
    )

    uv_tool, uv_plugin_resolve_script, platform, python_binary, data_digest = await MultiGet(
        Get(UvTool),
        Get(_UvPluginResolveScript),
        Get(Platform),
        Get(PythonBuildStandaloneBinary),
        Get(
            Digest,
            CreateDigest(
                [
                    FileContent(content=pyproject_content.encode(), path="pyproject.toml"),
                ]
            ),
        ),
    )

    cache_scope = (
        ProcessCacheScope.PER_SESSION
        if global_options.plugins_force_resolve
        else ProcessCacheScope.PER_RESTART_SUCCESSFUL
    )

    input_digest = await Get(
        Digest, MergeDigests([uv_plugin_resolve_script.digest, uv_tool.digest, data_digest])
    )

    env = await Get(
        EnvironmentVars, EnvironmentVarsRequest(["PATH", "HOME"], allowed=["PATH", "HOME"])
    )

    process = Process(
        argv=(
            python_binary.path,
            f"{{chroot}}/{uv_plugin_resolve_script.path}",
            "{chroot}",
            f"{uv_tool.exe}",
            "pyproject.toml",
        ),
        env=env,
        input_digest=input_digest,
        append_only_caches=python_binary.APPEND_ONLY_CACHES,
        description=f"Resolving plugins: {', '.join(req_strings)}",
        cache_scope=cache_scope,
    )

    workspace_process_execution_environment = ProcessExecutionEnvironment(
        environment_name=None,
        platform=platform.value,
        docker_image=None,
        remote_execution=False,
        remote_execution_extra_platform_properties=(),
        execute_in_workspace=True,
        keep_sandboxes="never",
    )

    result = await execute_process(process, workspace_process_execution_environment)
    print(f"uv result stdout:\n{result.stdout.decode()}")
    print(f"uv result stderr:\n{result.stderr.decode()}")
    if result.exit_code != 0:
        raise ValueError(f"Plugin resolution failed: stderr={result.stderr.decode()}")

    return ResolvedPluginDistributions(result.stdout.decode().strip().split("\n"))


@rule
async def resolve_plugins(
    request: PluginsRequest, global_options: GlobalOptions
) -> ResolvedPluginDistributions:
    if global_options.experimental_use_uv_for_plugin_resolution:
        return await resolve_plugins_via_uv(request=request, global_options=global_options)
    else:
        return await resolve_plugins_via_pex(request=request, global_options=global_options)


class PluginResolver:
    """Encapsulates the state of plugin loading.

    Plugin loading is inherently stateful, and so the system enviroment on `sys.path` will be
    mutated by each call to `PluginResolver.resolve`.
    """

    def __init__(
        self,
        scheduler: BootstrapScheduler,
        interpreter_constraints: InterpreterConstraints | None = None,
        inherit_existing_constraints: bool = True,
    ) -> None:
        self._scheduler = scheduler
        self._interpreter_constraints = interpreter_constraints
        self._inherit_existing_constraints = inherit_existing_constraints

    def resolve(
        self,
        options_bootstrapper: OptionsBootstrapper,
        env: CompleteEnvironmentVars,
        requirements: Iterable[str] = (),
    ) -> list[str]:
        """Resolves any configured plugins and adds them to the sys.path as a side effect."""

        def to_requirement(d):
            return f"{d.name}=={d.version}"

        distributions: list[importlib.metadata.Distribution] = []
        if self._inherit_existing_constraints:
            distributions = list(find_matching_distributions(None))

        request = PluginsRequest(
            self._interpreter_constraints,
            tuple(to_requirement(dist) for dist in distributions),
            tuple(requirements),
        )

        result = []
        for resolved_plugin_location in self._resolve_plugins(options_bootstrapper, env, request):
            # Activate any .pth files plugin wheels may have.
            orig_sys_path_len = len(sys.path)
            site.addsitedir(resolved_plugin_location)
            if len(sys.path) > orig_sys_path_len:
                result.append(resolved_plugin_location)

        return result

    def _resolve_plugins(
        self,
        options_bootstrapper: OptionsBootstrapper,
        env: CompleteEnvironmentVars,
        request: PluginsRequest,
    ) -> ResolvedPluginDistributions:
        session = self._scheduler.scheduler.new_session(
            "plugin_resolver",
            session_values=SessionValues(
                {
                    OptionsBootstrapper: options_bootstrapper,
                    CompleteEnvironmentVars: env,
                }
            ),
        )
        params = Params(request, determine_bootstrap_environment(session))
        return cast(
            ResolvedPluginDistributions,
            session.product_request(ResolvedPluginDistributions, params)[0],
        )


def rules():
    return [
        QueryRule(ResolvedPluginDistributions, [PluginsRequest, EnvironmentName]),
        *collect_rules(),
        *adhoc_binaries_rules(),
        *uv_rules(),
    ]
