# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from pathlib import Path
from typing import Optional

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.binaries.binary_tool import NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.engine.platform import Platform
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import file_option
from pants.util.dirutil import chmod_plus_x
from pants.util.memo import memoized_method, memoized_staticproperty


class ScalaFmtNativeUrlGenerator(BinaryToolUrlGenerator):

  _DIST_URL_FMT = 'https://github.com/scalameta/scalafmt/releases/download/v{version}/scalafmt-{system_id}.zip'

  _SYSTEM_ID = {
    'mac': 'macos',
    'linux': 'linux',
  }

  def generate_urls(self, version, host_platform):
    system_id = self._SYSTEM_ID[host_platform.os_name]
    return [self._DIST_URL_FMT.format(version=version, system_id=system_id)]


class ScalaFmtSubsystem(JvmToolMixin, NativeTool):
  options_scope = 'scalafmt'
  default_version = '2.3.1'
  default_fingerprint = 'ec219e20c604a324962c01de5621558fa08761ba63c5b455ec3acf34ff187d76'
  default_size_bytes = 16616182
  archive_type = 'zip'

  def get_external_url_generator(self):
    return ScalaFmtNativeUrlGenerator()

  @memoized_staticproperty
  def unzipped_inner_dir_platform_specific_name() -> str:
    return Platform.current.match({
      Platform.darwin: 'scalafmt-macos',
      Platform.linux: 'scalafmt-linux',
    })

  @memoized_method
  def select(self):
    """Reach into the unzipped directory and return the scalafmt executable.

    Also make sure to chmod +x the scalafmt executable, since the release zip doesn't do that.
    """
    extracted_dir = super().select()
    output_file = os.path.join(extracted_dir,
                               self.unzipped_inner_dir_platform_specific_name,
                               'scalafmt')
    chmod_plus_x(output_file)
    return output_file

  @property
  def use_native_image(self) -> bool:
    return bool(self.get_options().use_native_image)

  @property
  def configuration(self) -> Optional[Path]:
    maybe_file = self.get_options().configuration
    if maybe_file is None:
      return None
    return Path(maybe_file)

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--use-native-image', type=bool, advanced=True, fingerprint=False,
             help='Use a pre-compiled native-image for scalafmt.')
    register('--configuration', advanced=True, type=file_option, default=None, fingerprint=True,
              help='Path to scalafmt config file, if not specified default scalafmt config used')

    cls.register_jvm_tool(register,
                          'scalafmt',
                          classpath=[
                          JarDependency(org='com.geirsson',
                                        name='scalafmt-cli_2.11',
                                        rev='1.5.1')])
