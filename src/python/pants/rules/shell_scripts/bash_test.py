# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

import pants.rules.shell_scripts
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, FileContent, FilesContent
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.shell_scripts.bash import Bash, BashScriptRequest
from pants.rules.shell_scripts.bash import rules as bash_rules
from pants.testutil.subsystem.util import init_subsystems
from pants.testutil.test_base import TestBase
from pants.util.collections import assert_single_element
from pants.util.pkg_util import get_resource_string


class BashTest(TestBase):
  @classmethod
  def rules(cls):
    return [
      *super().rules(),
      *bash_rules(),
      RootRule(Bash.Factory),
    ]

  def setUp(self):
    super().setUp()
    init_subsystems([Bash.Factory])

  def test_writes_named_file_with_stderr(self):
    write_named_file_script_contents = get_resource_string(pants.rules.shell_scripts,
                                                           Path('example-bash-script.bash'))

    exe_req_with_bash_script = self.request_single_product(ExecuteProcessRequest, Params(
      BashScriptRequest(
        script=FileContent('whatever-i-want-to-name-the-script-in-the-hermetic-environment.bash',
                           bytes(write_named_file_script_contents)),
        base_exe_request=ExecuteProcessRequest(
          argv=('file-contents', 'output-file-name.txt', 'stderr-contents'),
          input_files=EMPTY_DIRECTORY_DIGEST,
          description='Execute a bash script which produces an output file and writes to stderr!',
          output_files=('output-file-name.txt',),
        ),
      ),
      Bash.Factory.global_instance(),
    ))

    bash_result = self.request_single_product(ExecuteProcessResult, exe_req_with_bash_script)

    assert bash_result.stderr.decode('utf-8') == 'stderr-contents\n'

    output_file = assert_single_element(
      self.request_single_product(FilesContent, bash_result.output_directory_digest))

    assert output_file.path == 'output-file-name.txt'
    assert output_file.content.decode('utf-8') == 'file-contents\n'
