# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import getpass
import os
import re
import socket
import time
from collections import OrderedDict

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_mkdir_for
from pants.version import VERSION


class RunInfo:
    """A little plaintext file containing very basic info about a pants run.

    Can only be appended to, never edited.
    """

    def __init__(self, info_file):
        self._info_file = info_file
        safe_mkdir_for(self._info_file)
        self._info = OrderedDict()
        if os.path.exists(self._info_file):
            with open(self._info_file, "r") as infile:
                info = infile.read()
            for m in re.finditer("""^([^:]+):(.*)$""", info, re.MULTILINE):
                self._info[m.group(1).strip()] = m.group(2).strip()

    def path(self):
        return self._info_file

    def get_info(self, key):
        return self._info.get(key, None)

    def __getitem__(self, key):
        ret = self.get_info(key)
        if ret is None:
            raise KeyError(key)
        return ret

    def get_as_dict(self):
        return self._info.copy()

    def add_info(self, key, val, ignore_errors=False, stringify=True):
        """Adds the given info and returns a dict composed of just this added info."""
        self.add_infos((key, val), ignore_errors=ignore_errors, stringify=stringify)

    def add_infos(self, *keyvals, **kwargs):
        """Adds the given info and returns a dict composed of just this added info."""
        kv_pairs = []
        for key, val in keyvals:
            key = key.strip()
            if kwargs.get("stringify", True):
                val = str(val).strip()
            if ":" in key:
                raise ValueError(f'info key "{key}" must not contain a colon.')
            kv_pairs.append((key, val))

        for k, v in kv_pairs:
            if k in self._info:
                raise ValueError(
                    f'info key "{k}" already exists with value {self._info[k]}. '
                    "Cannot add it again with value {v}."
                )
            self._info[k] = v

        try:
            with open(self._info_file, "a") as outfile:
                for k, v in kv_pairs:
                    outfile.write("{}: {}\n".format(k, v))
        except IOError:
            if not kwargs.get("ignore_errors", False):
                raise

    def add_basic_info(self, run_id, timestamp):
        """Adds basic build info."""
        datetime = time.strftime("%A %b %d, %Y %H:%M:%S", time.localtime(timestamp))
        user = getpass.getuser()
        machine = socket.gethostname()
        buildroot = get_buildroot()
        # TODO: Get rid of the redundant 'path' key once everyone is off it.
        self.add_infos(
            ("id", run_id),
            ("timestamp", timestamp),
            ("datetime", datetime),
            ("user", user),
            ("machine", machine),
            ("path", buildroot),
            ("buildroot", buildroot),
            ("version", VERSION),
        )
