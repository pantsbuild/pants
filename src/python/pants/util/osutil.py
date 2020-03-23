# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import errno
import logging
import os
import posix
from functools import reduce
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


OS_ALIASES = {
    "darwin": {"macos", "darwin", "macosx", "mac os x", "mac"},
    "linux": {"linux", "linux2"},
}

Pid = int


def get_os_name(uname_result: Optional[posix.uname_result] = None) -> str:
    """
    :API: public
    """
    if uname_result is None:
        uname_result = os.uname()
    return uname_result[0].lower()


def normalize_os_name(os_name: str) -> str:
    """
    :API: public
    """
    if os_name not in OS_ALIASES:
        for proper_name, aliases in OS_ALIASES.items():
            if os_name in aliases:
                return proper_name
        logger.warning(
            "Unknown operating system name: {bad}, known names are: {known}".format(
                bad=os_name, known=", ".join(sorted(known_os_names()))
            )
        )
    return os_name


def get_normalized_os_name() -> str:
    return normalize_os_name(get_os_name())


def all_normalized_os_names() -> List[str]:
    return list(OS_ALIASES.keys())


def known_os_names() -> Set[str]:
    return reduce(set.union, OS_ALIASES.values())


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
    except (IOError, OSError) as e:
        if e.errno in [errno.ESRCH, errno.EPERM]:
            pass
        elif e.errno == errno.EINVAL:
            raise ValueError(f"Invalid signal number {signum}: {e}", e)
        else:
            raise


# TODO: use this as the default value for the global --binaries-path-by-id option!
# pantsd testing fails saying no run trackers were created when I tried to do this.
SUPPORTED_PLATFORM_NORMALIZED_NAMES = {
    ("linux", "x86_64"): ("linux", "x86_64"),
    ("linux", "amd64"): ("linux", "x86_64"),
    ("linux", "i386"): ("linux", "i386"),
    ("linux", "i686"): ("linux", "i386"),
    ("darwin", "9"): ("mac", "10.5"),
    ("darwin", "10"): ("mac", "10.6"),
    ("darwin", "11"): ("mac", "10.7"),
    ("darwin", "12"): ("mac", "10.8"),
    ("darwin", "13"): ("mac", "10.9"),
    ("darwin", "14"): ("mac", "10.10"),
    ("darwin", "15"): ("mac", "10.11"),
    ("darwin", "16"): ("mac", "10.12"),
    ("darwin", "17"): ("mac", "10.13"),
}


def get_closest_mac_host_platform_pair(
    darwin_version_upper_bound: Optional[str] = None,
    platform_name_map: Dict[Tuple[str, str], Tuple[str, str]] = SUPPORTED_PLATFORM_NORMALIZED_NAMES,
) -> Tuple[Optional[str], Optional[str]]:
    """Return the (host, platform) pair for the highest known darwin version less than the bound."""
    darwin_versions = [int(x[1]) for x in platform_name_map if x[0] == "darwin"]

    if darwin_version_upper_bound is not None:
        bounded_darwin_versions = [
            v for v in darwin_versions if v <= int(darwin_version_upper_bound)
        ]
    else:
        bounded_darwin_versions = darwin_versions

    if not bounded_darwin_versions:
        return None, None
    max_darwin_version = str(max(bounded_darwin_versions))
    return platform_name_map[("darwin", max_darwin_version)]
