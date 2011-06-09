# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

__author__ = 'Brian Wickman'

import os
import stat
import base64
import pkgutil

class PexCreator(object):
  PEX_REPLACE_ZIP = '__PEX_CREATOR_ZIPFILE__'
  PEX_REPLACE_TARGET = '__PEX_CREATOR_TARGET__'
  PEX_FOOTER = 'pex_creator_footer.template'
  PEX_TEMPLATE = 'pex_creator.template'
  EGG_PARSER_REPLACE_STRING = '__EGG_PARSER_TEMPLATE__'
  EGG_PARSER = 'eggparser.py'

  def __init__(self, zip, target_name):
    self.zip = zip
    self.target_name = target_name

  @staticmethod
  def _read_footer():
    return pkgutil.get_data(__name__, PexCreator.PEX_FOOTER)

  @staticmethod
  def _read_template():
    return pkgutil.get_data(__name__, PexCreator.PEX_TEMPLATE)

  @staticmethod
  def _read_eggparser():
    return pkgutil.get_data(__name__, PexCreator.EGG_PARSER)

  @staticmethod
  def chmod_plus_x(path):
    path_mode = os.stat(path).st_mode
    path_mode &= int('777', 8)
    if path_mode & stat.S_IRUSR:
      path_mode |= stat.S_IXUSR
    if path_mode & stat.S_IRGRP:
      path_mode |= stat.S_IXGRP
    if path_mode & stat.S_IROTH:
      path_mode |= stat.S_IXOTH
    os.chmod(path, path_mode)

  def populated_template(self):
    template = PexCreator._read_template()
    template = template.replace(PexCreator.EGG_PARSER_REPLACE_STRING, PexCreator._read_eggparser())
    template = template.replace(PexCreator.PEX_REPLACE_ZIP, os.path.basename(self.zip))
    template = template.replace(PexCreator.PEX_REPLACE_TARGET, self.target_name)
    return template

  def build(self, pex_path):
    zip_fh = open(self.zip)
    zip_src = zip_fh.read()
    zip_fh.close()

    zip_src_b64 = base64.b64encode(zip_src)
    run_script = open(pex_path, 'w')
    run_script.write('#!/usr/bin/env python2.6\n\n')
    run_script.write(PexCreator._read_footer())
    run_script.write('EGG_B64 = """\n')
    for k in range(0, len(zip_src_b64), 80):
      run_script.write(zip_src_b64[k : k+80] + '\n')
    run_script.write('"""\n\n')
    run_script.write(self.populated_template())
    run_script.close()
    PexCreator.chmod_plus_x(pex_path)
    return pex_path
