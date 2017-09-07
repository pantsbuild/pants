# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.util.dirutil import safe_mkdir
from pants.util.process_handler import subprocess

from pants.contrib.android.targets.android_binary import AndroidBinary
from pants.contrib.android.tasks.android_task import AndroidTask


logger = logging.getLogger(__name__)


class Zipalign(AndroidTask):
  """Task to run zipalign, an archive alignment tool."""

  @classmethod
  def prepare(cls, options, round_manager):
    super(Zipalign, cls).prepare(options, round_manager)
    round_manager.require_data('release_apk')

  @staticmethod
  def is_zipaligntarget(target):
    """Determine whether the target is a candidate for the zipalign task."""
    return isinstance(target, AndroidBinary)

  def __init__(self, *args, **kwargs):
    super(Zipalign, self).__init__(*args, **kwargs)
    self._distdir = self.get_options().pants_distdir

  def _render_args(self, package, target):
    """Create arg list for the zipalign process.

    :param string package: Location of a signed apk product from the SignApk task.
    :param AndroidBinary target: Target to be zipaligned.
    """
    # Glossary of used zipalign flags:
    #   : '-f' is to force overwrite of existing outfile.
    #   :  '4' is the mandated byte-alignment boundaries. If not 4, zipalign doesn't do anything.
    #   :   Final two args are infile, outfile.
    output_name = '{0}.signed.apk'.format(target.manifest.package_name)
    outfile = os.path.join(self.zipalign_out(target), output_name)
    args = [self.zipalign_binary(target), '-f', '4', package, outfile]
    logger.debug('Executing: {0}'.format(' '.join(args)))
    return args

  def execute(self):
    targets = self.context.targets(self.is_zipaligntarget)
    for target in targets:

      def get_products_path(target):
        """Get path of target's apks that are signed with release keystores by SignApk task."""
        apks = self.context.products.get('release_apk')
        packages = apks.get(target)
        if packages:
          for tgts, products in packages.items():
            for prod in products:
              yield os.path.join(tgts, prod)

      packages = list(get_products_path(target))
      for package in packages:
        safe_mkdir(self.zipalign_out(target))
        args = self._render_args(package, target)
        with self.context.new_workunit(name='zipalign', labels=[WorkUnitLabel.MULTITOOL]) as workunit:
          returncode = subprocess.call(args, stdout=workunit.output('stdout'),
                                       stderr=workunit.output('stderr'))
          if returncode:
            raise TaskError('The zipalign process exited non-zero: {0}'.format(returncode))

  def zipalign_binary(self, target):
    """Return the appropriate zipalign binary."""
    zipalign_binary = os.path.join('build-tools', target.build_tools_version, 'zipalign')
    return self.android_sdk.register_android_tool(zipalign_binary)

  def zipalign_out(self, target):
    """Compute the outdir for the zipalign task."""
    return os.path.join(self._distdir, target.name)
