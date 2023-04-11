# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import errno
import getpass
import logging
import os
import platform
import posix
from functools import reduce

logger = logging.getLogger(__name__)


def _compute_cpu_count() -> int:
    # We use `sched_getaffinity()` to get the number of cores available to the process, rather than
    # the raw number of cores. This sometimes helps for containers to accurately report their # of
    # cores, rather than the host's.
    sched_getaffinity = getattr(os, "sched_getaffinity", None)
    if sched_getaffinity:
        return len(sched_getaffinity(0))
    cpu_count = os.cpu_count()
    if cpu_count:
        return cpu_count
    return 2


CPU_COUNT = _compute_cpu_count()


OS_ALIASES = {
    "macos": {"macos", "darwin", "macosx", "mac os x", "mac"},
    "linux": {"linux", "linux2"},
}

ARCH_ALIASES = {
    "x86_64": {"x86_64", "x86-64", "amd64"},
    "arm64": {"arm64", "aarch64"},
}

Pid = int


def get_arch_name(uname_result: posix.uname_result | None = None) -> str:
    """
    :API: public
    """
    if uname_result is None:
        uname_result = os.uname()
    return uname_result.machine.lower()


def get_os_name(uname_result: posix.uname_result | None = None) -> str:
    """
    :API: public
    """
    if uname_result is None:
        uname_result = os.uname()
    return uname_result.sysname.lower()


def normalize_arch_name(arch_name: str) -> str:
    """
    :API: public
    """
    return _normalize(arch_name, ARCH_ALIASES, "architecture")


def normalize_os_name(os_name: str) -> str:
    """
    :API: public
    """
    return _normalize(os_name, OS_ALIASES, "operating system")


def _normalize(name: str, aliases: dict[str, set[str]], warning_hint: str) -> str:
    for proper_name, alias_set in aliases.items():
        if name in alias_set:
            return proper_name
    else:
        logger.warning(
            "Unknown {hint} name: {bad}, known names are: {known}".format(
                hint=warning_hint, bad=name, known=", ".join(sorted(_values(aliases)))
            )
        )
        return name


def get_normalized_os_name() -> str:
    return normalize_os_name(get_os_name())


def get_normalized_arch_name() -> str:
    return normalize_arch_name(get_arch_name())


def is_macos_big_sur() -> bool:
    return hasattr(platform, "mac_ver") and platform.mac_ver()[0].startswith("11.")


def getuser() -> str:
    try:
        return getpass.getuser()
    except KeyError:
        # Work when running with a uid not associated with a user,
        # e.g., in a docker container with a host uid.
        return str(os.getuid())


def _values(aliases: dict[str, set[str]]) -> set[str]:
    return reduce(set.union, aliases.values())


# From kill(2) on OSX 10.13:
#     [EINVAL]           Sig is not a valid, supported signal number.
#
#     [EPERM]            The sending process is not the super-user and its effective user id does not match the effective user-id of the receiving process.  When signaling a process group, this error is returned if
#                        any members of the group could not be signaled.
#
#     [ESRCH]            No process or process group can be found corresponding to that specified by pid.
#
#     [ESRCH]            The process id was given as 0, but the sending process does not have a process group.
def safe_kill(pid: Pid, signum: int) -> None:
    """Kill a process with the specified signal, catching nonfatal errors."""
    assert isinstance(pid, Pid)
    assert isinstance(signum, int)
    try:
        os.kill(pid, signum)
    except OSError as e:
        if e.errno in [errno.ESRCH, errno.EPERM]:
            pass
        elif e.errno == errno.EINVAL:
            raise ValueError(f"Invalid signal number {signum}: {e}", e)
        else:
            raise
