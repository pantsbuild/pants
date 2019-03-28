# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import configparser
import os.path
import sys
from builtins import str

from packaging.version import Version

from pants.version import VERSION
from pants.base.exceptions import TaskError
from pants.task.task import Task
from pants.util.objects import enum

class GenerateConfig(Task):
  """Generate pants.ini with sensible defaults."""

  PANTS_INI = "pants.ini"

  class RuntimePythonVersion(enum(['2.7', '3.6', '3.7'])):
    pass

  class CustomConfigParser(configparser.ConfigParser):
    """We monkey-patch the write() function to allow us to write entries in the style `key: value`, 
       rather than `key:value` or `key : value`."""

    def write(self, fp):
      # Refer to https://github.com/jaraco/configparser/blob/294a985b759bddd3505ace54ecf56da39c56a302/src/backports/configparser/__init__.py#L916
      # for the original source.
      delimiter = ": "
      if self._defaults:
        self._write_section(fp, self.default_section, self._defaults.items(), delimiter)
      for section in self._sections:
        self._write_section(fp, section, self._sections[section].items(), delimiter)

  @classmethod
  def register_options(cls, register):
    super(GenerateConfig, cls).register_options(register)
    register('--new-pants-version', type=str, default=None,
             help='Pin pants_version so that Pants runs with this specific version.')
    register('--new-runtime-python-version', type=cls.RuntimePythonVersion, default=None,
             help='Pin pants_runtime_python_version so that Pants runs with this specific Python version.')

  def execute(self):
    target_pants_version = self.get_options().new_pants_version or VERSION
    python_version_may_be_specified = Version(target_pants_version) >= Version("1.15.0.dev4")
    if self.get_options().new_runtime_python_version:
      if not python_version_may_be_specified:
        raise TaskError("--new-runtime-python-version cannot be used with Pants versions earlier than "
                        "1.15.0.dev4 (you're using {})".format(target_pants_version))
      target_python_version = self.get_options().new_runtime_python_version.value
    else:
      interpreter_major_minor = ".".join(str(v) for v in sys.version_info[:2])
      target_python_version = interpreter_major_minor if python_version_may_be_specified else None

    config = self.CustomConfigParser()
    if os.path.isfile(self.PANTS_INI):
      config.read(self.PANTS_INI)

    config["GLOBAL"] = {"pants_version": target_pants_version}
    if target_python_version is not None:
      config["GLOBAL"]["pants_runtime_python_version"] = target_python_version

    with open(self.PANTS_INI, 'w') as f:
      config.write(f)
