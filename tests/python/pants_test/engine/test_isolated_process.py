# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import unittest
from builtins import str

from future.utils import text_type

from pants.engine.fs import (EMPTY_DIRECTORY_DIGEST, Digest, FileContent, FilesContent, PathGlobs,
                             Snapshot)
from pants.engine.isolated_process import (ExecuteProcessRequest, ExecuteProcessResult,
                                           FallibleExecuteProcessResult, ProcessExecutionFailure)
from pants.engine.rules import RootRule, rule
from pants.engine.scheduler import ExecutionError
from pants.engine.selectors import Get
from pants.util.contextutil import temporary_dir
from pants.util.objects import TypeCheckError, datatype
from pants_test.test_base import TestBase


class Concatted(datatype([('value', text_type)])): pass


class BinaryLocation(datatype([('bin_path', text_type)])):

  def __new__(cls, bin_path):
    this_object = super(BinaryLocation, cls).__new__(cls, text_type(bin_path))

    bin_path = this_object.bin_path

    if os.path.isfile(bin_path) and os.access(bin_path, os.X_OK):
      return this_object

    raise cls.make_type_error("path {} does not name an existing executable file."
                              .format(bin_path))


class ShellCat(datatype([('binary_location', BinaryLocation)])):
  """Wrapper class to show an example of using an auxiliary class (which wraps
  an executable) to generate an argv instead of doing it all in
  CatExecutionRequest. This can be used to encapsulate operations such as
  sanitizing command-line arguments which are specific to the executable, which
  can reduce boilerplate for generating ExecuteProcessRequest instances if the
  executable is used in different ways across multiple different types of
  process execution requests."""

  @property
  def bin_path(self):
    return self.binary_location.bin_path

  def argv_from_snapshot(self, snapshot):
    cat_file_paths = snapshot.files

    option_like_files = [p for p in cat_file_paths if p.startswith('-')]
    if option_like_files:
      raise ValueError(
        "invalid file names: '{}' look like command-line options"
        .format(option_like_files))

    # Add /dev/null to the list of files, so that cat doesn't hang forever if no files are in the
    # Snapshot.
    return (self.bin_path, "/dev/null") + tuple(cat_file_paths)


class CatExecutionRequest(datatype([('shell_cat', ShellCat), ('path_globs', PathGlobs)])): pass


@rule(Concatted, [CatExecutionRequest])
def cat_files_process_result_concatted(cat_exe_req):
  cat_bin = cat_exe_req.shell_cat
  cat_files_snapshot = yield Get(Snapshot, PathGlobs, cat_exe_req.path_globs)
  process_request = ExecuteProcessRequest(
    argv=cat_bin.argv_from_snapshot(cat_files_snapshot),
    input_files=cat_files_snapshot.directory_digest,
    description='cat some files',
  )
  cat_process_result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, process_request)
  yield Concatted(cat_process_result.stdout.decode('utf-8'))


def create_cat_stdout_rules():
  return [
    cat_files_process_result_concatted,
    RootRule(CatExecutionRequest),
  ]


class JavacVersionExecutionRequest(datatype([('binary_location', BinaryLocation)])):

  description = 'obtaining javac version'

  @property
  def bin_path(self):
    return self.binary_location.bin_path

  def gen_argv(self):
    return (self.bin_path, '-version',)


class JavacVersionOutput(datatype([('value', text_type)])): pass


@rule(JavacVersionOutput, [JavacVersionExecutionRequest])
def get_javac_version_output(javac_version_command):
  javac_version_proc_req = ExecuteProcessRequest(
    argv=javac_version_command.gen_argv(),
    description=javac_version_command.description,
    input_files=EMPTY_DIRECTORY_DIGEST,
  )
  javac_version_proc_result = yield Get(
    ExecuteProcessResult, ExecuteProcessRequest, javac_version_proc_req)

  yield JavacVersionOutput(text_type(javac_version_proc_result.stderr))


class JavacSources(datatype([('java_files', tuple)])):
  """Wrapper for the paths to include for Java source files.

  This shows an example of making a custom type to wrap generic types such as str to add usage
  context.

  See CatExecutionRequest and rules above for an example of using PathGlobs
  which does not introduce this additional layer of indirection.
  """


class JavacCompileRequest(datatype([
    ('binary_location', BinaryLocation),
    ('javac_sources', JavacSources),
])):

  @property
  def bin_path(self):
    return self.binary_location.bin_path

  def argv_from_source_snapshot(self, snapshot):
    return (self.bin_path,) + snapshot.files


class JavacCompileResult(datatype([
  ('stdout', text_type),
  ('stderr', text_type),
  ('directory_digest', Digest),
])): pass


# Note that this rule assumes that no additional classes are generated other than one for each
# source file, i.e. that there are no inner classes, extras generated by annotation processors, etc.
# This rule just serves as documentation for how rules can look - it is not intended to be
# exhaustively correct java compilation.
# This rule/test should be deleted when we have more real java rules (or anything else which serves
# as a suitable rule-writing example).
@rule(JavacCompileResult, [JavacCompileRequest])
def javac_compile_process_result(javac_compile_req):
  java_files = javac_compile_req.javac_sources.java_files
  for java_file in java_files:
    if not java_file.endswith(".java"):
      raise ValueError("Can only compile .java files but got {}".format(java_file))
  sources_snapshot = yield Get(Snapshot, PathGlobs, PathGlobs(java_files, ()))
  output_dirs = tuple({os.path.dirname(java_file) for java_file in java_files})
  process_request = ExecuteProcessRequest(
    argv=javac_compile_req.argv_from_source_snapshot(sources_snapshot),
    input_files=sources_snapshot.directory_digest,
    output_directories=output_dirs,
    description='javac compilation'
  )
  javac_proc_result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, process_request)

  stdout = javac_proc_result.stdout
  stderr = javac_proc_result.stderr

  yield JavacCompileResult(
    text_type(stdout),
    text_type(stderr),
    javac_proc_result.output_directory_digest,
  )


def create_javac_compile_rules():
  return [
    javac_compile_process_result,
    RootRule(JavacCompileRequest),
  ]


class ExecuteProcessRequestTest(unittest.TestCase):
  def _default_args_execute_process_request(self, argv=tuple(), env=None):
    env = env or dict()
    return ExecuteProcessRequest(
      argv=argv,
      description='',
      env=env,
      input_files=EMPTY_DIRECTORY_DIGEST,
      output_files=(),
    )

  def test_blows_up_on_invalid_args(self):
    try:
      self._default_args_execute_process_request()
    except ValueError:
      self.assertTrue(False, "should be able to construct without error")

    with self.assertRaises(TypeCheckError):
      self._default_args_execute_process_request(argv=1)
    with self.assertRaises(TypeCheckError):
      self._default_args_execute_process_request(argv='1')
    with self.assertRaises(TypeCheckError):
      self._default_args_execute_process_request(argv=('1',), env='foo=bar')


    with self.assertRaisesRegexp(TypeCheckError, "env"):
      ExecuteProcessRequest(
        argv=('1',),
        env=(),
        input_files='',
        output_files=(),
        output_directories=(),
        timeout_seconds=0.1,
        description=''
      )
    with self.assertRaisesRegexp(TypeCheckError, "input_files"):
      ExecuteProcessRequest(argv=('1',),
        env=dict(),
        input_files=3,
        output_files=(),
        output_directories=(),
        timeout_seconds=0.1,
        description=''
      )
    with self.assertRaisesRegexp(TypeCheckError, "output_files"):
      ExecuteProcessRequest(
        argv=('1',),
        env=dict(),
        input_files=EMPTY_DIRECTORY_DIGEST,
        output_files=("blah"),
        output_directories=(),
        timeout_seconds=0.1,
        description=''
      )
    with self.assertRaisesRegexp(TypeCheckError, "timeout"):
      ExecuteProcessRequest(
        argv=('1',),
        env=dict(),
        input_files=EMPTY_DIRECTORY_DIGEST,
        output_files=("blah"),
        output_directories=(),
        timeout_seconds=None,
        description=''
      )

  def test_create_from_snapshot_with_env(self):
    req = ExecuteProcessRequest(
      argv=('foo',),
      description="Some process",
      env={'VAR': 'VAL'},
      input_files=EMPTY_DIRECTORY_DIGEST,
    )
    self.assertEqual(req.env, ('VAR', 'VAL'))


class IsolatedProcessTest(TestBase, unittest.TestCase):

  @classmethod
  def rules(cls):
    return super(IsolatedProcessTest, cls).rules() + [
      RootRule(JavacVersionExecutionRequest),
      get_javac_version_output,
    ] + create_cat_stdout_rules() + create_javac_compile_rules()

  def test_integration_concat_with_snapshots_stdout(self):

    self.create_file('f1', 'one\n')
    self.create_file('f2', 'two\n')

    cat_exe_req = CatExecutionRequest(
      ShellCat(BinaryLocation('/bin/cat')),
      PathGlobs(include=['f*']),
    )

    concatted = self.scheduler.product_request(Concatted, [cat_exe_req])[0]
    self.assertEqual(Concatted('one\ntwo\n'), concatted)

  def test_javac_version_example(self):
    request = JavacVersionExecutionRequest(BinaryLocation('/usr/bin/javac'))
    result = self.scheduler.product_request(JavacVersionOutput, [request])[0]
    self.assertIn('javac', result.value)

  def test_write_file(self):
    request = ExecuteProcessRequest(
      argv=("/bin/bash", "-c", "echo -n 'European Burmese' > roland"),
      description="echo roland",
      output_files=("roland",),
      input_files=EMPTY_DIRECTORY_DIGEST,
    )

    execute_process_result = self.scheduler.product_request(
      ExecuteProcessResult,
      [request],
    )[0]

    self.assertEqual(
      execute_process_result.output_directory_digest,
      Digest(
        fingerprint=text_type("63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16"),
        serialized_bytes_length=80,
      )
    )

    files_content_result = self.scheduler.product_request(
      FilesContent,
      [execute_process_result.output_directory_digest],
    )[0]

    self.assertEqual(
      files_content_result.dependencies,
      (FileContent("roland", b"European Burmese"),)
    )

  def test_exercise_python_side_of_timeout_implementation(self):
    # Local execution currently doesn't support timeouts,
    # but this allows us to ensure that all of the setup
    # on the python side does not blow up.

    request = ExecuteProcessRequest(
      argv=("/bin/bash", "-c", "/bin/sleep 1; echo -n 'European Burmese'"),
      timeout_seconds=0.1,
      description='sleepy-cat',
      input_files=EMPTY_DIRECTORY_DIGEST,
    )

    self.scheduler.product_request(ExecuteProcessResult, [request])[0]

  def test_javac_compilation_example_success(self):
    self.create_dir('simple')
    self.create_file('simple/Simple.java', '''package simple;
// Valid java. Totally complies.
class Simple {

}''')

    request = JavacCompileRequest(
      BinaryLocation('/usr/bin/javac'),
      JavacSources((u'simple/Simple.java',)),
    )

    result = self.scheduler.product_request(JavacCompileResult, [request])[0]
    files_content = self.scheduler.product_request(FilesContent, [result.directory_digest])[0].dependencies

    self.assertEqual(
      tuple(sorted((
        "simple/Simple.java",
        "simple/Simple.class",
      ))),
      tuple(sorted(file.path for file in files_content))
    )

    self.assertGreater(len(files_content[0].content), 0)

  def test_javac_compilation_example_failure(self):
    self.create_dir('simple')
    self.create_file('simple/Broken.java', '''package simple;
class Broken {
  NOT VALID JAVA!
}''')

    request = JavacCompileRequest(
      BinaryLocation('/usr/bin/javac'),
      JavacSources(('simple/Broken.java',))
    )

    with self.assertRaises(ExecutionError) as cm:
      self.scheduler.product_request(JavacCompileResult, [request])[0]
    e = cm.exception.wrapped_exceptions[0]
    self.assertIsInstance(e, ProcessExecutionFailure)
    self.assertEqual(1, e.exit_code)
    self.assertIn('javac compilation', str(e))
    self.assertIn(b"NOT VALID JAVA", e.stderr)

  def test_jdk(self):
    with temporary_dir() as temp_dir:
      with open(os.path.join(temp_dir, 'roland'), 'w') as f:
        f.write('European Burmese')
      request = ExecuteProcessRequest(
        argv=('/bin/cat', '.jdk/roland'),
        input_files=EMPTY_DIRECTORY_DIGEST,
        description='cat JDK roland',
        jdk_home=temp_dir,
      )
      result = self.scheduler.product_request(ExecuteProcessResult, [request])[0]
      self.assertEqual(result.stdout, b'European Burmese')

  def test_fallible_failing_command_returns_exited_result(self):
    request = ExecuteProcessRequest(
      argv=("/bin/bash", "-c", "exit 1"),
      description='one-cat',
      input_files=EMPTY_DIRECTORY_DIGEST,
    )

    result = self.scheduler.product_request(FallibleExecuteProcessResult, [request])[0]

    self.assertEqual(result.exit_code, 1)

  def test_non_fallible_failing_command_raises(self):
    request = ExecuteProcessRequest(
      argv=("/bin/bash", "-c", "exit 1"),
      description='one-cat',
      input_files=EMPTY_DIRECTORY_DIGEST,
    )

    with self.assertRaises(ExecutionError) as cm:
      self.scheduler.product_request(ExecuteProcessResult, [request])
    self.assertIn("process 'one-cat' failed with exit code 1.", str(cm.exception))
