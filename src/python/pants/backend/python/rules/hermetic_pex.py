# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Any, Iterable, Mapping, Optional

from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest
from pants.engine.process import Process
from pants.python.python_setup import PythonSetup
from pants.util.strutil import create_path_env_var


class HermeticPex:
    """A mixin for types that provide an executable Pex that should be executed hermetically."""

    def create_process(
        self,
        python_setup: PythonSetup,
        subprocess_encoding_environment: SubprocessEncodingEnvironment,
        *,
        pex_path: str,
        pex_args: Iterable[str],
        description: str,
        input_digest: Digest,
        env: Optional[Mapping[str, str]] = None,
        **kwargs: Any
    ) -> Process:
        """Creates an Process that will run a PEX hermetically.

        :param python_setup: The parameters for selecting python interpreters to use when invoking
                             the PEX.
        :param subprocess_encoding_environment: The locale settings to use for the PEX invocation.
        :param pex_path: The path within `input_files` of the PEX file (or directory if a loose
                         pex).
        :param pex_args: The arguments to pass to the PEX executable.
        :param description: A description of the process execution to be performed.
        :param input_digest: The directory digest that contains the PEX itself and any input files
                             it needs to run against.
        :param env: The environment to run the PEX in.
        :param **kwargs: Any additional :class:`Process` kwargs to pass through.
        """

        # NB: we use the hardcoded and generic bin name `python`, rather than something dynamic like
        # `sys.executable`, to ensure that the interpreter may be discovered both locally and in remote
        # execution (so long as `env` is populated with a `PATH` env var and `python` is discoverable
        # somewhere on that PATH). This is only used to run the downloaded PEX tool; it is not
        # necessarily the interpreter that PEX will use to execute the generated .pex file.
        # TODO(#7735): Set --python-setup-interpreter-search-paths differently for the host and target
        # platforms, when we introduce platforms in https://github.com/pantsbuild/pants/issues/7735.
        argv = ("python", pex_path, *pex_args)

        hermetic_env = dict(
            PATH=create_path_env_var(python_setup.interpreter_search_paths),
            PEX_INHERIT_PATH="false",
            PEX_IGNORE_RCFILES="true",
            **subprocess_encoding_environment.invocation_environment_dict,
        )
        if env:
            hermetic_env.update(env)

        return Process(
            argv=argv,
            input_digest=input_digest,
            description=description,
            env=hermetic_env,
            **kwargs,
        )
