# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Tuple

from pants.engine.platform import Platform
from pants.engine.process import BinaryPathRequest, BinaryPaths, InteractiveProcess
from pants.engine.rules import Get, collect_rules, rule
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@frozen_after_init
@dataclass(unsafe_hash=True)
class OpenFilesRequest:
    files: Tuple[PurePath, ...]
    error_if_open_not_found: bool

    def __init__(self, files: Iterable[PurePath], *, error_if_open_not_found: bool = True) -> None:
        self.files = tuple(files)
        self.error_if_open_not_found = error_if_open_not_found


@dataclass(frozen=True)
class OpenFiles:
    processes: Tuple[InteractiveProcess, ...]


@rule
async def find_open_program(request: OpenFilesRequest, plat: Platform) -> OpenFiles:
    open_program_name = "open" if plat == Platform.darwin else "xdg-open"
    open_program_paths = await Get(
        BinaryPaths,
        BinaryPathRequest(binary_name=open_program_name, search_path=("/bin", "/usr/bin")),
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

    if plat == Platform.darwin:
        processes = [
            InteractiveProcess(
                argv=(open_program_paths.first_path.path, *(str(f) for f in request.files)),
                run_in_workspace=True,
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
                hermetic_env=False,
            )
            for f in request.files
        ]

    return OpenFiles(tuple(processes))


def rules():
    return collect_rules()
