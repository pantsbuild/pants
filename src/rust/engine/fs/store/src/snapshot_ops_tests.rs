// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::fs::create_dir_all;
use std::os::unix::fs::symlink;
use std::path::Path;
use std::sync::Arc;

use fs::{
    DirectoryDigest, GlobExpansionConjunction, PosixFS, PreparedPathGlobs, StrictGlobMatching,
};
use testutil::make_file;

use crate::{
    snapshot_tests::{expand_all_sorted, setup, STR, STR2},
    OneOffStoreFileByDigest, Snapshot, SnapshotOps, SubsetParams,
};

async fn get_duplicate_rolands<T: SnapshotOps>(
    store_wrapper: T,
    base_path: &Path,
    posix_fs: Arc<PosixFS>,
    digester: OneOffStoreFileByDigest,
) -> (DirectoryDigest, Snapshot, Snapshot) {
    create_dir_all(base_path.join("subdir")).unwrap();

    make_file(&base_path.join("subdir/roland1"), STR.as_bytes(), 0o600);
    let path_stats1 = expand_all_sorted(posix_fs).await;
    let snapshot1 = Snapshot::from_path_stats(digester.clone(), path_stats1)
        .await
        .unwrap();

    let (_store2, tempdir2, posix_fs2, digester2) = setup();
    create_dir_all(tempdir2.path().join("subdir")).unwrap();
    make_file(
        &tempdir2.path().join("subdir/roland2"),
        STR2.as_bytes(),
        0o600,
    );
    let path_stats2 = expand_all_sorted(posix_fs2).await;
    let snapshot2 = Snapshot::from_path_stats(digester2, path_stats2)
        .await
        .unwrap();

    let merged_digest = store_wrapper
        .merge(vec![snapshot1.clone().into(), snapshot2.clone().into()])
        .await
        .unwrap();

    (merged_digest, snapshot1, snapshot2)
}

fn make_subset_params(globs: &[&str]) -> SubsetParams {
    let globs = PreparedPathGlobs::create(
        globs.iter().map(|s| s.to_string()).collect(),
        StrictGlobMatching::Ignore,
        GlobExpansionConjunction::AllMatch,
    )
    .unwrap();
    SubsetParams { globs }
}

#[tokio::test]
async fn subset_single_files() {
    let (store, tempdir, posix_fs, digester) = setup();

    let (merged_digest, snapshot1, snapshot2) =
        get_duplicate_rolands(store.clone(), tempdir.path(), posix_fs.clone(), digester).await;

    let subset_params1 = make_subset_params(&["subdir/roland1"]);
    let subset_roland1 = store
        .clone()
        .subset(merged_digest.clone(), subset_params1)
        .await
        .unwrap();
    assert_eq!(subset_roland1, snapshot1.into());

    let subset_params2 = make_subset_params(&["subdir/roland2"]);
    let subset_roland2 = store
        .clone()
        .subset(merged_digest, subset_params2)
        .await
        .unwrap();
    assert_eq!(subset_roland2, snapshot2.into());
}

#[tokio::test]
async fn subset_symlink() {
    // Make the first snapshot with a file
    let (store, tempdir1, posix_fs1, digester1) = setup();
    create_dir_all(tempdir1.path().join("subdir")).unwrap();
    make_file(
        &tempdir1.path().join("subdir/roland1"),
        STR.as_bytes(),
        0o600,
    );
    let snapshot_with_real_file =
        Snapshot::from_path_stats(digester1.clone(), expand_all_sorted(posix_fs1).await)
            .await
            .unwrap();

    // Make the second snapshot with a symlink pointing to the file in the first snapshot.
    let (_store2, tempdir2, posix_fs2, digester2) = setup();
    create_dir_all(tempdir2.path().join("subdir")).unwrap();
    symlink("./roland1", tempdir2.path().join("subdir/roland2")).unwrap();
    let snapshot_with_symlink =
        Snapshot::from_path_stats(digester2, expand_all_sorted(posix_fs2).await)
            .await
            .unwrap();

    let merged_digest = store
        .merge(vec![
            snapshot_with_real_file.clone().into(),
            snapshot_with_symlink.clone().into(),
        ])
        .await
        .unwrap();

    let subset_params = make_subset_params(&["subdir/roland2"]);
    let subset_symlink = store
        .clone()
        .subset(merged_digest.clone(), subset_params)
        .await
        .unwrap();
    // NB: The digest subset should still be the symlink.
    assert_eq!(subset_symlink, snapshot_with_symlink.into());
}

#[tokio::test]
async fn subset_recursive_wildcard() {
    let (store, tempdir, posix_fs, digester) = setup();

    let (merged_digest, snapshot1, _) =
        get_duplicate_rolands(store.clone(), tempdir.path(), posix_fs.clone(), digester).await;

    let subset_params1 = make_subset_params(&["subdir/**"]);
    let subset_roland1 = store
        .clone()
        .subset(merged_digest.clone(), subset_params1)
        .await
        .unwrap();
    assert_eq!(merged_digest, subset_roland1);

    // **/* is a commonly-used alias for **.
    let subset_params2 = make_subset_params(&["subdir/**/*"]);
    let subset_roland2 = store
        .clone()
        .subset(merged_digest.clone(), subset_params2)
        .await
        .unwrap();
    assert_eq!(merged_digest, subset_roland2);

    // ** should not include explicitly excluded files
    let subset_params3 = make_subset_params(&["!subdir/roland2", "subdir/**"]);
    let subset_roland3 = store
        .clone()
        .subset(merged_digest.clone(), subset_params3)
        .await
        .unwrap();
    assert_eq!(subset_roland3, snapshot1.clone().into());

    // ** should not include explicitly excluded files
    let subset_params4 = make_subset_params(&["!subdir/roland2", "**"]);
    let subset_roland4 = store
        .clone()
        .subset(merged_digest, subset_params4)
        .await
        .unwrap();
    assert_eq!(subset_roland4, snapshot1.into());
}
