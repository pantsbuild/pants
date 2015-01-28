# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import base64
import os
import shutil

def atomic_copy(src, dst):
  tmp = base64.b64encode(os.urandom(16), ',.')
  tmp_dst = dst + tmp
  shutil.copyfile(src, tmp_dst)
  os.rename(tmp_dst, dst)
