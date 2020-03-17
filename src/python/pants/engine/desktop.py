# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC
from dataclasses import dataclass
from pathlib import PurePath
from typing import ClassVar, Iterable, Iterator

from pants.engine.console import Console
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.util.osutil import get_os_name
from pants.util.strutil import safe_shlex_join


@dataclass
class Opener(ABC):
    console: Console
    runner: InteractiveRunner

    program: ClassVar[str]

    def _iter_openers(self, files: Iterable[PurePath]) -> Iterator[InteractiveProcessRequest]:
        # N.B.: We cannot mark this method @abc.abstractmethod due to:
        #   https://github.com/python/mypy/issues/5374
        raise NotImplementedError()

    def open(self, files: Iterable[PurePath]) -> None:
        for request in self._iter_openers(files):
            open_command = safe_shlex_join(request.argv)
            try:
                result = self.runner.run_local_interactive_process(request)
                if result.process_exit_code != 0:
                    self.console.print_stderr(
                        f"Failed to open files for viewing using `{open_command}` - received exit "
                        f"code {result.process_exit_code}."
                    )
            except Exception as e:
                self.console.print_stderr(
                    f"Failed to open files for viewing using " f"`{open_command}`: {e}"
                )
                self.console.print_stderr(
                    f"Ensure {self.program} is installed on your `PATH` and " f"re-run this goal."
                )


class DarwinOpener(Opener):
    program = "open"

    def _iter_openers(self, files: Iterable[PurePath]) -> Iterator[InteractiveProcessRequest]:
        yield InteractiveProcessRequest(
            argv=(self.program, *(str(f) for f in files)), run_in_workspace=True
        )


class LinuxOpener(Opener):
    program = "xdg-open"

    def _iter_openers(self, files: Iterable[PurePath]) -> Iterator[InteractiveProcessRequest]:
        for f in files:
            yield InteractiveProcessRequest(argv=(self.program, str(f)), run_in_workspace=True)


_OPENERS_BY_OSNAME = {"darwin": DarwinOpener, "linux": LinuxOpener}


def ui_open(console: Console, runner: InteractiveRunner, files: Iterable[PurePath]) -> None:
    osname = get_os_name()
    opener_type = _OPENERS_BY_OSNAME.get(osname)
    if opener_type is None:
        console.print_stderr(f"Could not open {' '.join(map(str, files))} for viewing.")
        console.print_stderr(
            f"Opening files for viewing is currently not supported for the "
            f"{osname} operating system."
        )
        return

    opener = opener_type(console, runner)
    opener.open(files)
