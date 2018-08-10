# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pex.interpreter import PythonInterpreter
from pex.platforms import Platform


logger = logging.getLogger(__name__)


def _interpreter_str(interp):
  ident = interp.identity
  return ('PythonInterpreter({binary!r}, {identity!r} with extended info: '
          '(abbr_impl: {abbr_impl!r}, impl_ver: {impl_ver!r}, abi_tag: {abi_tag!r}))'
          .format(binary=interp.binary,
                  identity=ident,
                  abbr_impl=ident.abbr_impl,
                  impl_ver=ident.impl_ver,
                  abi_tag=ident.abi_tag))


def expand_and_maybe_adjust_platform(interpreter, platform):
  """Adjusts `platform` if it is 'current' and does not match the given `interpreter` platform.

  :param interpreter: The target interpreter for the given `platform`.
  :type interpreter: :class:`pex.interpreter.PythonInterpreter`
  :param platform: The platform name to expand and maybe adjust.
  :type platform: text
  :returns: The `platform`, potentially adjusted.
  :rtype: :class:`pex.platforms.Platform`
  """
  # TODO(John Sirois): Kill all usages when https://github.com/pantsbuild/pex/issues/511 is fixed.
  cur_plat = Platform.current()

  if cur_plat.platform != Platform.create(platform).platform:
    # IE: Say we're on OSX and platform was 'linux-x86_64' or 'linux_x86_64-cp-27-cp27mu'.
    return Platform.create(platform)

  ii = interpreter.identity
  if (ii.abbr_impl, ii.impl_ver, ii.abi_tag) == (cur_plat.impl, cur_plat.version, cur_plat.abi):
    # IE: Say we're on Linux and platform was 'current' or 'linux-x86_64' or
    # 'linux_x86_64-cp-27-cp27mu'and the current extended platform info matches the given
    # interpreter exactly.
    return cur_plat

  # Otherwise we need to adjust the platform to match a local interpreter different from the
  # currently executing interpreter.
  interpreter_platform = Platform(platform=cur_plat.platform,
                                  impl=ii.abbr_impl,
                                  version=ii.impl_ver,
                                  abi=ii.abi_tag)

  logger.debug("""
Modifying given platform of {given_platform!r}:
Using the current platform of {current_platform!r}
Under current interpreter {current_interpreter!r}
        
To match given interpreter {given_interpreter!r}.
        
Calculated platform: {calculated_platform!r}""".format(
    given_platform=platform,
    current_platform=cur_plat,
    current_interpreter=_interpreter_str(PythonInterpreter.get()),
    given_interpreter=_interpreter_str(interpreter),
    calculated_platform=interpreter_platform)
  )

  return interpreter_platform
