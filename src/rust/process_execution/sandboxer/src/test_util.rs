// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use ::fs::{DigestTrie, DirectoryDigest, TypedPath};
use bytes::Bytes;
use hashing::Digest;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use store::StoreCliOpt;

pub async fn prep_store(dir_path: &Path) -> (StoreCliOpt, DirectoryDigest) {
    let local_store_path: PathBuf = dir_path.join("lmdb_store");
    fs::create_dir(&local_store_path).unwrap();

    let store_cli_opt = StoreCliOpt::new_local_only(local_store_path);
    let store = store_cli_opt
        .create_store(task_executor::Executor::new())
        .await
        .unwrap();

    let file_bytes = Bytes::from("Hello, world!");
    let file_digests = HashMap::from_iter(vec![(
        PathBuf::from("subdir/greeting.txt"),
        Digest::of_bytes(&file_bytes),
    )]);
    for _ in file_digests.values() {
        store
            .store_file_bytes(file_bytes.clone(), false)
            .await
            .unwrap();
    }

    let tree = DigestTrie::from_unique_paths(
        vec![TypedPath::File {
            path: file_digests.keys().next().unwrap(),
            is_executable: false,
        }],
        &file_digests,
    )
    .unwrap();

    let dir_digest: DirectoryDigest = tree.into();
    store
        .record_digest_trie(dir_digest.tree.clone().unwrap(), true)
        .await
        .unwrap();

    (store_cli_opt, dir_digest)
}
