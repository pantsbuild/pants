# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.android.tasks.android_task import AndroidTask


class KeyError(Exception):
  pass
  # need an err "We could not find a key at DEFAULT you need to xxxxxxxx

class JarsignerTask(AndroidTask):
  """Sign Android packages with keystore"""

  # For debug releases, we are using the debug key created with an install
  # of the Android SDK. This uses a keystore with a known passphrase and a key with a
  # known passphrase. But there is
  # no rule that is the debug key the org will want. I would like to include a debug key with
  # pants that matches the one from the SDK.

  def __init__(self, *args, **kwargs):
    super(JarsignerTask, self).__init__(*args, **kwargs)
    self._android_dist = self.android_sdk

  def prepare(self, round_manager):
    round_manager.require_data('apk')
    pass

  def debug_fields(self):
    pass
  def execute(self):
    print("I am taking a metro to see the giraffe show")
