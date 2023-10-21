// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::python::TypeId;

pub struct Types {
    pub directory_digest: TypeId,
    pub file_digest: TypeId,
    pub snapshot: TypeId,
    pub paths: TypeId,
    pub file_content: TypeId,
    pub file_entry: TypeId,
    pub symlink_entry: TypeId,
    pub directory: TypeId,
    pub digest_contents: TypeId,
    pub digest_entries: TypeId,
    pub path_globs: TypeId,
    pub merge_digests: TypeId,
    pub add_prefix: TypeId,
    pub remove_prefix: TypeId,
    pub create_digest: TypeId,
    pub digest_subset: TypeId,
    pub native_download_file: TypeId,
    pub platform: TypeId,
    pub process: TypeId,
    pub process_config_from_environment: TypeId,
    pub process_result: TypeId,
    pub process_result_metadata: TypeId,
    pub coroutine: TypeId,
    pub session_values: TypeId,
    pub run_id: TypeId,
    pub interactive_process: TypeId,
    pub interactive_process_result: TypeId,
    pub engine_aware_parameter: TypeId,
    pub docker_resolve_image_request: TypeId,
    pub docker_resolve_image_result: TypeId,
}
