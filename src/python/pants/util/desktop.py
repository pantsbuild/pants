# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from typing import Sequence

from pants.util.osutil import get_os_name


class IdeaNotFoundException(Exception):
    """Could not find Idea executable."""


class OpenError(Exception):
    """Indicates an error opening a file in a desktop application."""


def _mac_open_with_idea(file_: str, lookup_paths: list) -> None:
    ideaPath = next((path for path in lookup_paths if os.path.isdir(path)), None)
    if ideaPath is not None:
        subprocess.call(["open", "-a", ideaPath, file_])
    else:
        raise IdeaNotFoundException(
            "Could not find Idea executable in the following locations:\n{}".format(
                "\n".join(lookup_paths)
            )
        )


def _mac_open(files: Sequence[str]) -> None:
    subprocess.call(["open"] + list(files))


def _linux_open_with_idea(file_: str, lookup_paths: list) -> None:
    cmd = "idea"
    if not _cmd_exists(cmd):
        raise OpenError(
            "The program '{}' isn't in your PATH. Please install and re-run this "
            "goal.".format(cmd)
        )
    subprocess.Popen(["nohup", cmd, file_])


def _linux_open(files: Sequence[str]) -> None:
    cmd = "xdg-open"
    if not _cmd_exists(cmd):
        raise OpenError(
            "The program '{}' isn't in your PATH. Please install and re-run this "
            "goal.".format(cmd)
        )
    for f in list(files):
        subprocess.call([cmd, f])


# From: http://stackoverflow.com/questions/377017/test-if-executable-exists-in-python
def _cmd_exists(cmd: str) -> bool:
    return (
        subprocess.call(
            ["/usr/bin/which", cmd], shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        == 0
    )


_OPENER_BY_OS = {"darwin": _mac_open, "linux": _linux_open}

_IDEA_BY_OS = {"darwin": _mac_open_with_idea, "linux": _linux_open_with_idea}


def idea_open(file_: str, lookup_paths: list) -> None:
    """Attempts to open the given files using the preferred desktop viewer or editor.

    :raises :class:`OpenError`: if there is a problem opening any of the files.
    """
    if file_:
        osname = get_os_name()
        opener = _IDEA_BY_OS.get(osname)
        if opener:
            opener(file_, lookup_paths)
        else:
            raise OpenError("Open currently not supported for " + osname)


def ui_open(*files: str) -> None:
    """Attempts to open the given files using the preferred desktop viewer or editor.

    :raises :class:`OpenError`: if there is a problem opening any of the files.
    """
    if files:
        osname = get_os_name()
        opener = _OPENER_BY_OS.get(osname)
        if opener:
            opener(files)
        else:
            raise OpenError("Open currently not supported for " + osname)
