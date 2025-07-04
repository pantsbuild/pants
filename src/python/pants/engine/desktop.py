# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePath

from pants.core.environments.rules import ChosenLocalEnvironmentName, EnvironmentName
from pants.core.util_rules.system_binaries import BinaryPathRequest, find_binary
from pants.engine.internals.platform_rules import complete_environment_vars, current_platform
from pants.engine.process import InteractiveProcess
from pants.engine.rules import collect_rules, concurrently, implicitly, rule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpenFilesRequest:
    files: tuple[PurePath, ...]
    error_if_open_not_found: bool

    def __init__(self, files: Iterable[PurePath], *, error_if_open_not_found: bool = True) -> None:
        object.__setattr__(self, "files", tuple(files))
        object.__setattr__(self, "error_if_open_not_found", error_if_open_not_found)


@dataclass(frozen=True)
class OpenFiles:
    processes: tuple[InteractiveProcess, ...]


@rule
async def find_open_program(
    request: OpenFilesRequest,
    local_environment_name: ChosenLocalEnvironmentName,
) -> OpenFiles:
    plat, complete_env = await concurrently(
        current_platform(**implicitly({local_environment_name.val: EnvironmentName})),
        complete_environment_vars(**implicitly(local_environment_name.val)),
    )
    open_program_name = "open" if plat.is_macos else "xdg-open"
    open_program_paths = await find_binary(
        **implicitly(
            {
                BinaryPathRequest(
                    binary_name=open_program_name, search_path=("/bin", "/usr/bin")
                ): BinaryPathRequest,
                local_environment_name.val: EnvironmentName,
            }
        )
    )
    if not open_program_paths.first_path:
        error = (
            f"Could not find the program '{open_program_name}' on `/bin` or `/usr/bin`, so cannot "
            f"open the files {sorted(request.files)}."
        )
        if request.error_if_open_not_found:
            raise OSError(error)
        logger.error(error)
        return OpenFiles(())

    if plat.is_macos:
        processes = [
            InteractiveProcess(
                argv=(open_program_paths.first_path.path, *(str(f) for f in request.files)),
                run_in_workspace=True,
                restartable=True,
            )
        ]
    else:
        processes = [
            InteractiveProcess(
                argv=(open_program_paths.first_path.path, str(f)),
                run_in_workspace=True,
                # The xdg-open binary needs many environment variables to work properly. In addition
                # to the various XDG_* environment variables, DISPLAY and other X11 variables are
                # required. Instead of attempting to track all of these we just export the full user
                # environment since this is not a cached process.
                env=complete_env,
                restartable=True,
            )
            for f in request.files
        ]

    return OpenFiles(tuple(processes))


def rules():
    return collect_rules()
