# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys

from colors import blue, green, red


class Console:
  def __init__(self, stdout=None, stderr=None, use_colors=True):
    self._stdout = stdout or sys.stdout
    self._stderr = stderr or sys.stderr
    self._use_colors = use_colors

  @property
  def stdout(self):
    return self._stdout

  @property
  def stderr(self):
    return self._stderr

  def write_stdout(self, payload):
    self.stdout.write(payload)

  def write_stderr(self, payload):
    self.stderr.write(payload)

  def print_stdout(self, payload, end='\n'):
    print(payload, file=self.stdout, end=end)

  def print_stderr(self, payload, end='\n'):
    print(payload, file=self.stderr, end=end)

  def flush(self):
    self.stdout.flush()
    self.stderr.flush()

  def _safe_color(self, text, color):
    """We should only output color when the global flag --colors is enabled."""
    return color(text) if self._use_colors else text

  def blue(self, text):
    return self._safe_color(text, blue)

  def green(self, text):
    return self._safe_color(text, green)

  def red(self, text):
    return self._safe_color(text, red)
