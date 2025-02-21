# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os
import shlex
import site
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent  # noqa: PNT20
from typing import cast

from pkg_resources import Requirement, WorkingSet
from pkg_resources import working_set as global_working_set

from pants.backend.python.subsystems.python_native_code import PythonNativeCodeSubsystem
from pants.backend.python.subsystems.repos import PythonRepos
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex_cli_tool import PexPEX
from pants.backend.python.util_rules.pex_cli_tool import rules as pex_cli_tool_rules
from pants.backend.python.util_rules.pex_environment import PythonExecutable
from pants.core.subsystems.python_bootstrap import PythonBootstrap
from pants.core.util_rules.adhoc_binaries import PythonBuildStandaloneBinary
from pants.core.util_rules.environments import determine_bootstrap_environment
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.collection import DeduplicatedCollection
from pants.engine.env_vars import CompleteEnvironmentVars, EnvironmentVars, EnvironmentVarsRequest
from pants.engine.environment import EnvironmentName
from pants.engine.fs import CreateDigest, Digest, Directory, FileContent, MergeDigests
from pants.engine.internals.selectors import Params
from pants.engine.internals.session import SessionValues
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, QueryRule, collect_rules, rule
from pants.init.bootstrap_scheduler import BootstrapScheduler
from pants.option.global_options import GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Script:
    path: PurePath

    @property
    def argv0(self) -> str:
        return f"./{self.path}" if self.path.parent == PurePath() else str(self.path)


@dataclass(frozen=True)
class _VenvScript:
    script: _Script
    content: FileContent


# Vendored and simplified copy of `pants.backend.python.util_rules.pex.VenvScriptWriter` so that
# plugin resolution does not have to instantiate a `CompletePexEnvironment`.
def _create_venv_script(
    *,
    bash: BashBinary,
    script_path: PurePath,
    venv_executable: PurePath,
    env: Mapping[str, str],
    venv_dir: PurePath,
    pbs_python: PythonBuildStandaloneBinary,
    pex_filename: str,
) -> _VenvScript:
    env_vars = shlex.join(f"{name}={value}" for name, value in env.items())

    target_venv_executable = shlex.quote(str(venv_executable))
    raw_execute_pex_args = [
        pbs_python.path,
        f"./{pex_filename}",
    ]
    execute_pex_args = " ".join(
        f"$(adjust_relative_paths {shlex.quote(arg)})" for arg in raw_execute_pex_args
    )

    script = dedent(
        f"""\
        #!{bash.path}
        set -euo pipefail

        # N.B.: This relies on BASH_SOURCE which has been available since bash-3.0, released in
        # 2004. It will either contain the absolute path of the venv script or it will contain
        # the relative path from the CWD to the venv script. Either way, we know the venv script
        # parent directory is the sandbox root directory.
        SANDBOX_ROOT="${{BASH_SOURCE%/*}}"

        function adjust_relative_paths() {{
            local value0="$1"
            shift
            if [ "${{value0:0:1}}" == "/" ]; then
                # Don't relativize absolute paths.
                echo "${{value0}}" "$@"
            else
                # N.B.: We convert all relative paths to paths relative to the sandbox root so
                # this script works when run with a PWD set somewhere else than the sandbox
                # root.
                #
                # There are two cases to consider. For the purposes of example, assume PWD is
                # `/tmp/sandboxes/abc123/foo/bar`; i.e.: the rule API sets working_directory to
                # `foo/bar`. Also assume `config/tool.yml` is the relative path in question.
                #
                # 1. If our BASH_SOURCE is  `/tmp/sandboxes/abc123/pex_shim.sh`; so our
                #    SANDBOX_ROOT is `/tmp/sandboxes/abc123`, we calculate
                #    `/tmp/sandboxes/abc123/config/tool.yml`.
                # 2. If our BASH_SOURCE is instead `../../pex_shim.sh`; so our SANDBOX_ROOT is
                #    `../..`, we calculate `../../config/tool.yml`.
                echo "${{SANDBOX_ROOT}}/${{value0}}" "$@"
            fi
        }}

        export {env_vars}
        export PEX_ROOT="$(adjust_relative_paths ${{PEX_ROOT}})"

        execute_pex_args="{execute_pex_args}"
        target_venv_executable="$(adjust_relative_paths {target_venv_executable})"
        venv_dir="$(adjust_relative_paths {shlex.quote(str(venv_dir))})"

        # Let PEX_TOOLS invocations pass through to the original PEX file since venvs don't come
        # with tools support.
        if [ -n "${{PEX_TOOLS:-}}" ]; then
            exec ${{execute_pex_args}} "$@"
        fi

        # If the seeded venv has been removed from the PEX_ROOT, we re-seed from the original
        # `--venv` mode PEX file.
        if [ ! -e "${{venv_dir}}" ]; then
            PEX_INTERPRETER=1 ${{execute_pex_args}} -c ''
        fi

        exec "${{target_venv_executable}}" "$@"
        """
    )

    return _VenvScript(
        script=_Script(script_path),
        content=FileContent(path=str(script_path), content=script.encode(), is_executable=True),
    )


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


@rule
async def resolve_plugins(
    request: PluginsRequest,
    global_options: GlobalOptions,
    pex_cli_tool: PexPEX,
    python_bootstrap: PythonBootstrap,
    python_setup: PythonSetup,
    python_repos: PythonRepos,
    python_native_code: PythonNativeCodeSubsystem.EnvironmentAware,
    bash: BashBinary,
    pbs_python: PythonBuildStandaloneBinary,
) -> ResolvedPluginDistributions:
    """This rule resolves plugins directly using Pex and exposes the absolute paths of their dists.

    NB: This relies on the fact that PEX constructs venvs in a stable location (within the
    `named_caches` directory), but consequently needs to disable the process cache: see the
    ProcessCacheScope reference in the body.
    """
    req_strings = sorted(global_options.plugins + request.requirements)
    if not req_strings:
        return ResolvedPluginDistributions()

    existing_env = await Get(EnvironmentVars, EnvironmentVarsRequest(["PATH"]))

    _PEX_ROOT_DIRNAME = "pex_root"
    PANTS_PLUGINS_PEX_FILENAME = "pants_plugins.pex"

    pex_root = PurePath(".cache") / _PEX_ROOT_DIRNAME

    tmp_digest = await Get(Digest, CreateDigest([Directory(".tmp")]))
    input_digests: list[Digest] = [pex_cli_tool.digest, tmp_digest]

    append_only_caches: dict[str, str] = {
        _PEX_ROOT_DIRNAME: str(pex_root),
    }
    append_only_caches.update(pbs_python.APPEND_ONLY_CACHES)

    python: PythonExecutable | None = None
    if not request.interpreter_constraints:
        python = PythonExecutable.fingerprinted(
            sys.executable, ".".join(map(str, sys.version_info[:3])).encode("utf8")
        )

    env: dict[str, str] = {
        "LANG": "en_US.UTF-8",
        "PEX_IGNORE_RCFILES": "true",
        "PEX_ROOT": str(pex_root),
        **(python_native_code.subprocess_env_vars),
    }
    path_env = existing_env.get("PATH", "")
    if path_env:
        env["PATH"] = path_env

    if python:
        env["PEX_PYTHON"] = python.path
    else:
        env["PEX_PYTHON_PATH"] = os.pathsep.join(python_bootstrap.interpreter_search_paths)

    args: list[str] = [
        pbs_python.path,
        pex_cli_tool.exe,
        "--tmpdir=.tmp",
        "--jobs=1",
        f"--pip-version={python_setup.pip_version}",
        f"--python-path={os.pathsep.join(python_bootstrap.interpreter_search_paths)}",
        f"--output-file={PANTS_PLUGINS_PEX_FILENAME}",
        "--venv=prepend",
        "--seed=verbose",  # Seed venv into PEX_ROOT and outputs JSON blob with location of that venv.
        "--no-venv-site-packages-copies",  # TODO: Correct?
        # An internal-only runs on a single machine, and pre-installing wheels is wasted work in
        # that case (see https://github.com/pex-tool/pex/issues/2292#issuecomment-1854582647 for
        # analysis).
        "--no-pre-install-wheels",
        "--sources-directory=source_files",
        *req_strings,
        "--no-pypi",
        *(f"--index={index}" for index in python_repos.indexes),
        *(f"--find-links={repo}" for repo in python_repos.find_links),
        *(
            [f"--manylinux={python_setup.manylinux}"]
            if python_setup.manylinux
            else ["--no-manylinux"]
        ),
        "--resolver-version=pip-2020-resolver",
        "--layout=packed",
    ]

    if python:
        args.append(f"--python={python.path}")
        append_only_caches.update(python.append_only_caches)

    if request.constraints:
        constraints_file = "__constraints.txt"
        constraints_content = "\n".join([str(constraint) for constraint in request.constraints])
        input_digests.append(
            await Get(
                Digest,
                CreateDigest([FileContent(constraints_file, constraints_content.encode())]),
            )
        )
        args.extend(["--constraints", constraints_file])

    merged_input_digest = await Get(Digest, MergeDigests(input_digests))

    plugins_pex_result = await Get(
        ProcessResult,
        Process(
            argv=args,
            input_digest=merged_input_digest,
            description=f"Resolving plugins: {', '.join(req_strings)}",
            append_only_caches=FrozenDict(append_only_caches),
            env=env,
            output_files=[PANTS_PLUGINS_PEX_FILENAME],
        ),
    )

    seed_info = json.loads(plugins_pex_result.stdout.decode())
    abs_pex_root = PurePath(seed_info["pex_root"])
    abs_pex_path = PurePath(seed_info["pex"])
    venv_rel_dir = abs_pex_path.relative_to(abs_pex_root).parent

    script_path = PurePath("pants_plugins_pex_shim.sh")
    venv_dir = pex_root / venv_rel_dir

    venv_script = _create_venv_script(
        bash=bash,
        script_path=script_path,
        venv_executable=venv_dir / "pex",
        env=env,
        venv_dir=venv_dir,
        pbs_python=pbs_python,
        pex_filename=PANTS_PLUGINS_PEX_FILENAME,
    )

    venv_script_digest = await Get(Digest, CreateDigest([venv_script.content]))

    # NB: We run this Process per-restart because it (intentionally) leaks named cache
    # paths in a way that invalidates the Process-cache. See the method doc.
    cache_scope = (
        ProcessCacheScope.PER_SESSION
        if global_options.plugins_force_resolve
        else ProcessCacheScope.PER_RESTART_SUCCESSFUL
    )

    plugins_path_input_digest = await Get(
        Digest, MergeDigests([venv_script_digest, plugins_pex_result.output_digest])
    )

    plugins_path_result = await Get(
        ProcessResult,
        Process(
            argv=[
                venv_script.script.argv0,
                "-c",
                "import os, site; print(os.linesep.join(site.getsitepackages()))",
            ],
            input_digest=plugins_path_input_digest,
            description="Extracting plugin locations",
            level=LogLevel.DEBUG,
            append_only_caches=FrozenDict(append_only_caches),
            cache_scope=cache_scope,
        ),
    )

    return ResolvedPluginDistributions(plugins_path_result.stdout.decode().strip().split("\n"))


class PluginResolver:
    """Encapsulates the state of plugin loading for the given WorkingSet.

    Plugin loading is inherently stateful, and so this class captures the state of the WorkingSet at
    creation time, even though it will be mutated by each call to `PluginResolver.resolve`. This
    makes the inputs to each `resolve(..)` call idempotent, even if the output is not.
    """

    def __init__(
        self,
        scheduler: BootstrapScheduler,
        interpreter_constraints: InterpreterConstraints | None = None,
        working_set: WorkingSet | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._working_set = working_set or global_working_set
        self._interpreter_constraints = interpreter_constraints

    def resolve(
        self,
        options_bootstrapper: OptionsBootstrapper,
        env: CompleteEnvironmentVars,
        requirements: Iterable[str] = (),
    ) -> WorkingSet:
        """Resolves any configured plugins and adds them to the working_set."""
        request = PluginsRequest(
            self._interpreter_constraints,
            tuple(dist.as_requirement() for dist in self._working_set),
            tuple(requirements),
        )

        for resolved_plugin_location in self._resolve_plugins(options_bootstrapper, env, request):
            site.addsitedir(
                resolved_plugin_location
            )  # Activate any .pth files plugin wheels may have.
            self._working_set.add_entry(resolved_plugin_location)
        return self._working_set

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
            session.product_request(ResolvedPluginDistributions, [params])[0],
        )


def rules():
    return [
        *collect_rules(),
        QueryRule(ResolvedPluginDistributions, (PluginsRequest, EnvironmentName)),
        *pex_cli_tool_rules(),
    ]
