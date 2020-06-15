// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::core::{Function, TypeId};

pub struct Types {
  pub construct_directory_digest: Function,
  pub directory_digest: TypeId,
  pub construct_snapshot: Function,
  pub snapshot: TypeId,
  pub construct_file_content: Function,
  pub construct_files_content: Function,
  pub files_content: TypeId,
  pub construct_process_result: Function,
  pub construct_materialize_directories_results: Function,
  pub construct_materialize_directory_result: Function,
  pub address: TypeId,
  pub path_globs: TypeId,
  pub merge_digests: TypeId,
  pub add_prefix: TypeId,
  pub remove_prefix: TypeId,
  pub input_files_content: TypeId,
  pub dir: TypeId,
  pub file: TypeId,
  pub link: TypeId,
  pub platform: TypeId,
  pub multi_platform_process: TypeId,
  pub process_result: TypeId,
  pub coroutine: TypeId,
  pub url_to_fetch: TypeId,
  pub string: TypeId,
  pub bytes: TypeId,
  pub construct_interactive_process_result: Function,
  pub interactive_process: TypeId,
  pub interactive_process_result: TypeId,
  pub snapshot_subset: TypeId,
  pub construct_platform: Function,
}
