// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::core::TypeId;

pub struct Types {
  pub directory_digest: TypeId,
  pub snapshot: TypeId,
  pub file_content: TypeId,
  pub digest_contents: TypeId,
  pub materialize_directories_results: TypeId,
  pub materialize_directory_result: TypeId,
  pub address: TypeId,
  pub path_globs: TypeId,
  pub merge_digests: TypeId,
  pub add_prefix: TypeId,
  pub remove_prefix: TypeId,
  pub create_digest: TypeId,
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
  pub interactive_process: TypeId,
  pub interactive_process_result: TypeId,
  pub snapshot_subset: TypeId,
}
