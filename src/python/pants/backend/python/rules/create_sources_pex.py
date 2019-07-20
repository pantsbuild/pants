# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Set

from pants.backend.python.rules.download_pex_bin import DownloadedPexBin
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.engine.fs import Digest, DirectoriesToMerge, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get
from pants.source.source_root import SourceRoot, SourceRootConfig
from pants.util.objects import datatype, string_type, hashable_string_list
from pants.util.strutil import create_path_env_var


class SourcesPexRequest(datatype([
  ('output_filename', string_type),
  ('sources_snapshot', Snapshot)
])):
  pass


class SourcesPex(datatype([
  ('directory_digest', Digest),
  ('source_roots', hashable_string_list)
])):
  pass


@rule(SourcesPex, [SourcesPexRequest, DownloadedPexBin, SourceRootConfig, PythonSetup])
def create_sources_pex(request, pex_bin, source_root_config, python_setup):
  """Returns a PEX with the provided source and resource files.

  The key reason we have this rule is to properly handle source roots, e.g. so that Python files
  are able to import `from pants.util import strutil` from the file path
  `src/python/pants/util/strutil.py`."""

  source_roots = source_root_config.get_source_roots()
  source_roots_set: Set[SourceRoot] = {
    source_roots.find_by_path(fp) for fp in request.sources_snapshot.files
  }

  env = {"PATH": create_path_env_var(python_setup.interpreter_search_paths)}
  input_digest = yield Get(Digest, DirectoriesToMerge(
    directories=(pex_bin.directory_digest, request.sources_snapshot.directory_digest)
  ))

  argv = ["python", f"./{pex_bin.executable}", "--output-file", request.output_filename]
  for source_root in source_roots_set:
    argv.append(f"--sources-directory={source_root.path}")

  execute_process_request = ExecuteProcessRequest(
    argv=tuple(argv),
    env=env,
    input_files=input_digest,
    description=f"Create a sources PEX: {', '.join(request.sources_snapshot.files)}",
    output_files=(request.output_filename,),
  )

  result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, execute_process_request)
  yield SourcesPex(
    directory_digest=result.output_directory_digest,
    source_roots=tuple(source_root.path for source_root in source_roots_set),
  )


def rules():
  return [
    create_sources_pex,
    optionable_rule(SourceRootConfig),
    optionable_rule(PythonSetup),
  ]
