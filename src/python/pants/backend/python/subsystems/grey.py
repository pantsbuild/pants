# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.engine.fs import Digest, FileContent, InputFilesContent
from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.option.custom_types import file_option
from pants.subsystem.subsystem import Subsystem


# Highjack the `Line.__str__` function from black.py and replace it with one that
# formats with 2 spaces indent.
# Note: when we update black's version, we will need to manually make sure that this
# monkey patch remains in sync with the upstream code.
# See: https://github.com/psf/black/blob/master/black.py
grey_patch_content = b'''
import itertools
import black

def str_with_two_chars_indent(self) -> str:
    """Render the line."""
    if not self:
        return "\\n"

    indent = "  " * self.depth
    leaves = iter(self.leaves)
    first = next(leaves)
    res = f"{first.prefix}{indent}{first.value}"
    for leaf in leaves:
        res += str(leaf)
    for comment in itertools.chain.from_iterable(self.comments.values()):
        res += str(comment)
    return res + "\\n"


black.Line.__str__ = str_with_two_chars_indent

black.patched_main()
'''


@dataclass (frozen=True)
class GreyPatchDigest:
  entry_point: str
  digest: Digest


@rule
def patch_black_into_grey() -> GreyPatchDigest:
  # Materialize a "grey.py" file with an entry point: "grey", which behaves like black but
  # formats with a two spaces indentation.
  grey_patch_digest = yield Get(Digest, InputFilesContent((
      FileContent(path = "grey.py", content = grey_patch_content, is_executable = False),
  )))
  yield GreyPatchDigest("grey", grey_patch_digest)


class Grey(Subsystem):
  options_scope = 'black_with_two_spaces_indent'
  default_interpreter_constraints = ["CPython>=3.6"]

  def get_requirement_specs(self):
    return ['black==19.3b0', 'setuptools']

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--config', advanced=True, type=file_option, fingerprint=True,
             help="Path to formatting tool's config file")

def rules():
  return [patch_black_into_grey]
