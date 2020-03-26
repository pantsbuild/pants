# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, cast

from pants.backend.python.rules.download_pex_bin import DownloadedPexBin
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest
from pants.engine.isolated_process import ExecuteProcessRequest
from pants.engine.rules import RootRule, rule, subsystem_rule
from pants.python.python_setup import PythonSetup
from pants.subsystem.subsystem import Subsystem
from pants.util.strutil import create_path_env_var


@dataclass(frozen=True)
class HermeticPexRequest:
    exe_req: ExecuteProcessRequest


@dataclass(frozen=True)
class HermeticPexResult:
    exe_req: ExecuteProcessRequest


class HermeticPex(Subsystem):
    options_scope = 'hermetic-pex-creation'

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register('--python-executable-name', type=str, default='python',
                 help='The python executable to search for in --python-setup-interpreter-search-paths '
                      'when creating a pex with the v2 python backend.')
        register('--use-pex-cache', type=bool, default=False,
                 help='Whether to enable the pex local cache when executing hermetically.')

    @property
    def python_executable_name(self) -> str:
        return cast(str, self.get_options().python_executable_name)

    @property
    def use_pex_cache(self) -> bool:
        return cast(bool, self.get_options().use_pex_cache)


@rule
def make_hermetic_pex_exe_request(
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    downloaded_pex_bin: DownloadedPexBin,
    hermetic_pex_factory: HermeticPex,
    req: HermeticPexRequest
) -> HermeticPexResult:
    """Creates an ExecuteProcessRequest that will run a PEX hermetically.

    :param python_setup: The parameters for selecting python interpreters to use when invoking the
                         PEX.
    :param subprocess_encoding_environment: The locale settings to use for the PEX invocation.
    :param pex_path: The path within `input_files` of the PEX file (or directory if a loose pex).
    :param pex_args: The arguments to pass to the PEX executable.
    :param description: A description of the process execution to be performed.
    :param input_files: The files that contain the pex itself and any input files it needs to run
                        against.
    :param env: The environment to run the PEX in.
    :param **kwargs: Any additional :class:`ExecuteProcessRequest` kwargs to pass through.
    """
    orig_exe_req = req.exe_req

    pex_path = downloaded_pex_bin.executable

    hermetic_env = orig_exe_req.env_dict.copy()
    hermetic_env.update(
        PATH=create_path_env_var(python_setup.interpreter_search_paths_ensure_directories),
        # We ask Pex to --disable-cache so we shouldn't also set a PEX_ROOT (asking it to
        # cache).
        PEX_ROOT="",
        PEX_INHERIT_PATH="false",
        PEX_IGNORE_RCFILES="true",
        **subprocess_encoding_environment.invocation_environment_dict
    )

    input_files = orig_exe_req.input_files
    if not input_files:
        input_files = downloaded_pex_bin.directory_digest

    cache_args = []
    if not hermetic_pex_factory.use_pex_cache:
        cache_args.append('--disable-cache')

    # NB: we use the hardcoded and generic bin name `python`, rather than something dynamic like
    # `sys.executable`, to ensure that the interpreter may be discovered both locally and in remote
    # execution (so long as `env` is populated with a `PATH` env var and `python` is discoverable
    # somewhere on that PATH). This is only used to run the downloaded PEX tool; it is not
    # necessarily the interpreter that PEX will use to execute the generated .pex file.
    # TODO(#7735): Set --python-setup-interpreter-search-paths differently for the host and target
    # platforms, when we introduce platforms in https://github.com/pantsbuild/pants/issues/7735.
    python_exe_name = hermetic_pex_factory.python_executable_name
    argv = (
        python_exe_name, downloaded_pex_bin.executable,
        *cache_args,
        *orig_exe_req.argv,
    )

    modified_exe_req = dataclasses.replace(
        orig_exe_req,
        argv=argv,
        env=hermetic_env,
        input_files=input_files,
    )
    return HermeticPexResult(modified_exe_req)


def rules():
    return [
        subsystem_rule(HermeticPex),
        RootRule(HermeticPexRequest),
        make_hermetic_pex_exe_request,
    ]
