// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::convert::TryInto;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use hashing::{Digest, Fingerprint, EMPTY_DIGEST};

use testutil::data::TestDirectory;
use testutil::make_file;

use crate::{OneOffStoreFileByDigest, RelativePath, Snapshot, SnapshotOps, Store, StoreError};
use fs::{
    Dir, DirectoryDigest, File, GitignoreStyleExcludes, GlobExpansionConjunction, GlobMatching,
    PathGlobs, PathStat, PosixFS, StrictGlobMatching, SymlinkBehavior,
};

pub const STR: &str = "European Burmese";
pub const STR2: &str = "asdf";

pub fn setup() -> (
    Store,
    tempfile::TempDir,
    Arc<PosixFS>,
    OneOffStoreFileByDigest,
) {
    let executor = task_executor::Executor::new();
    // TODO: Pass a remote CAS address through.
    let store = Store::local_only(
        executor.clone(),
        tempfile::Builder::new()
            .prefix("lmdb_store")
            .tempdir()
            .unwrap(),
    )
    .unwrap();
    let dir = tempfile::Builder::new().prefix("root").tempdir().unwrap();
    let ignorer = GitignoreStyleExcludes::create(vec![]).unwrap();
    let posix_fs = Arc::new(PosixFS::new(dir.path(), ignorer, executor).unwrap());
    let file_saver = OneOffStoreFileByDigest::new(store.clone(), posix_fs.clone(), true);
    (store, dir, posix_fs, file_saver)
}

#[tokio::test]
async fn snapshot_one_file() {
    let (_, dir, posix_fs, digester) = setup();

    let file_name = PathBuf::from("roland");
    make_file(&dir.path().join(&file_name), STR.as_bytes(), 0o600);

    let path_stats = expand_all_sorted(posix_fs).await;
    let snapshot = Snapshot::from_path_stats(digester, path_stats)
        .await
        .unwrap();
    assert_eq!(
        snapshot.digest,
        Digest::new(
            Fingerprint::from_hex_string(
                "63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16",
            )
            .unwrap(),
            80,
        )
    );
    assert_eq!(snapshot.files(), vec![PathBuf::from("roland")]);
    assert_eq!(snapshot.directories(), Vec::<PathBuf>::new());
}

#[tokio::test]
async fn snapshot_recursive_directories() {
    let (_, dir, posix_fs, digester) = setup();

    let cats = PathBuf::from("cats");
    let roland = cats.join("roland");
    std::fs::create_dir_all(dir.path().join(cats)).unwrap();
    make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

    let path_stats = expand_all_sorted(posix_fs).await;
    let snapshot = Snapshot::from_path_stats(digester, path_stats)
        .await
        .unwrap();
    assert_eq!(
        snapshot.digest,
        Digest::new(
            Fingerprint::from_hex_string(
                "8b1a7ea04eaa2527b35683edac088bc826117b53b7ec6601740b55e20bce3deb",
            )
            .unwrap(),
            78,
        )
    );
    assert_eq!(snapshot.files(), vec![PathBuf::from("cats/roland")]);
    assert_eq!(snapshot.directories(), vec![PathBuf::from("cats")]);
}

#[tokio::test]
async fn snapshot_from_digest() {
    let (store, dir, posix_fs, digester) = setup();

    let cats = PathBuf::from("cats");
    let roland = cats.join("roland");
    std::fs::create_dir_all(dir.path().join(cats)).unwrap();
    make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

    let path_stats = expand_all_sorted(posix_fs).await;
    let expected_snapshot = Snapshot::from_path_stats(digester, path_stats)
        .await
        .unwrap();

    // Confirm that the digest can be loaded either from memory (using a DirectoryDigest with a
    // tree attached), or from disk (using one without).

    // From memory.
    assert_eq!(
        expected_snapshot,
        Snapshot::from_digest(store.clone(), expected_snapshot.clone().into())
            .await
            .unwrap()
    );

    // From disk.
    store
        .ensure_directory_digest_persisted(expected_snapshot.clone().into())
        .await
        .unwrap();
    assert_eq!(
        expected_snapshot,
        Snapshot::from_digest(
            store,
            DirectoryDigest::from_persisted_digest(expected_snapshot.digest)
        )
        .await
        .unwrap()
    );
}

#[tokio::test]
async fn snapshot_recursive_directories_including_empty() {
    let (_, dir, posix_fs, digester) = setup();

    let cats = PathBuf::from("cats");
    let roland = cats.join("roland");
    let dogs = PathBuf::from("dogs");
    let llamas = PathBuf::from("llamas");
    std::fs::create_dir_all(dir.path().join(&cats)).unwrap();
    std::fs::create_dir_all(dir.path().join(&dogs)).unwrap();
    std::fs::create_dir_all(dir.path().join(&llamas)).unwrap();
    make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

    let sorted_path_stats = expand_all_sorted(posix_fs).await;
    let mut unsorted_path_stats = sorted_path_stats.clone();
    unsorted_path_stats.reverse();
    let snapshot = Snapshot::from_path_stats(digester, unsorted_path_stats)
        .await
        .unwrap();
    assert_eq!(
        snapshot.digest,
        Digest::new(
            Fingerprint::from_hex_string(
                "fbff703bdaac62accf2ea5083bcfed89292073bf710ef9ad14d9298c637e777b",
            )
            .unwrap(),
            232,
        ),
    );
    assert_eq!(snapshot.files(), vec![PathBuf::from("cats/roland")]);
    assert_eq!(
        snapshot.directories(),
        vec![
            PathBuf::from("cats"),
            PathBuf::from("dogs"),
            PathBuf::from("llamas")
        ]
    );
}

#[tokio::test]
async fn merge_directories_two_files() {
    let (store, _, _, _) = setup();

    let containing_roland = TestDirectory::containing_roland();
    let containing_treats = TestDirectory::containing_treats();

    store
        .record_directory(&containing_roland.directory(), false)
        .await
        .expect("Storing roland directory");
    store
        .record_directory(&containing_treats.directory(), false)
        .await
        .expect("Storing treats directory");

    let result = store
        .merge(vec![
            containing_treats.directory_digest(),
            containing_roland.directory_digest(),
        ])
        .await;

    assert_eq!(
        result,
        Ok(TestDirectory::containing_roland_and_treats().directory_digest())
    );
}

#[tokio::test]
async fn merge_directories_clashing_files() {
    let (store, _, _, _) = setup();

    let containing_roland = TestDirectory::containing_roland();
    let containing_wrong_roland = TestDirectory::containing_wrong_roland();

    store
        .record_directory(&containing_roland.directory(), false)
        .await
        .expect("Storing roland directory");
    store
        .record_directory(&containing_wrong_roland.directory(), false)
        .await
        .expect("Storing wrong roland directory");

    let err = store
        .merge(vec![
            containing_roland.directory_digest(),
            containing_wrong_roland.directory_digest(),
        ])
        .await
        .expect_err("Want error merging");

    assert!(
        format!("{err:?}").contains("roland"),
        "Want error message to contain roland but was: {err:?}"
    );
}

#[tokio::test]
async fn merge_directories_same_files() {
    let (store, _, _, _) = setup();

    let containing_roland = TestDirectory::containing_roland();
    let containing_roland_and_treats = TestDirectory::containing_roland_and_treats();

    store
        .record_directory(&containing_roland.directory(), false)
        .await
        .expect("Storing roland directory");
    store
        .record_directory(&containing_roland_and_treats.directory(), false)
        .await
        .expect("Storing treats directory");

    let result = store
        .merge(vec![
            containing_roland.directory_digest(),
            containing_roland_and_treats.directory_digest(),
        ])
        .await;

    assert_eq!(
        result,
        Ok(TestDirectory::containing_roland_and_treats().directory_digest())
    );
}

#[tokio::test]
async fn snapshot_merge_two_files() {
    let (store, tempdir, _, digester) = setup();

    let common_dir_name = "tower";
    let common_dir = PathBuf::from(common_dir_name);

    let dir = make_dir_stat(tempdir.path(), &common_dir);
    let file1 = make_file_stat(
        tempdir.path(),
        &common_dir.join("roland"),
        STR.as_bytes(),
        false,
    );
    let file2 = make_file_stat(
        tempdir.path(),
        &common_dir.join("susannah"),
        STR.as_bytes(),
        true,
    );

    let snapshot1 = Snapshot::from_path_stats(digester.clone(), vec![dir.clone(), file1.clone()])
        .await
        .unwrap();

    let snapshot2 = Snapshot::from_path_stats(digester, vec![dir.clone(), file2.clone()])
        .await
        .unwrap();

    let merged = store
        .merge(vec![snapshot1.into(), snapshot2.into()])
        .await
        .unwrap();
    store
        .ensure_directory_digest_persisted(merged.clone())
        .await
        .unwrap();
    let merged_root_directory = store.load_directory(merged.as_digest()).await.unwrap();

    assert_eq!(merged_root_directory.files.len(), 0);
    assert_eq!(merged_root_directory.directories.len(), 1);

    let merged_child_dirnode = merged_root_directory.directories[0].clone();
    let merged_child_dirnode_digest: Result<Digest, String> = merged_child_dirnode
        .digest
        .map(|d| d.try_into())
        .unwrap_or(Ok(EMPTY_DIGEST));
    let merged_child_directory = store
        .load_directory(merged_child_dirnode_digest.unwrap())
        .await
        .unwrap();

    assert_eq!(merged_child_dirnode.name, common_dir_name);
    assert_eq!(
        merged_child_directory
            .files
            .iter()
            .map(|filenode| filenode.name.clone())
            .collect::<Vec<_>>(),
        vec!["roland".to_string(), "susannah".to_string()],
    );
}

#[tokio::test]
async fn snapshot_merge_same_file() {
    let (store, tempdir, _, digester) = setup();

    let file = make_file_stat(
        tempdir.path(),
        &PathBuf::from("roland"),
        STR.as_bytes(),
        false,
    );

    // When the file is the exact same, merging should succeed.
    let snapshot1 = Snapshot::from_path_stats(digester.clone(), vec![file.clone()])
        .await
        .unwrap();
    let snapshot1_cloned = Snapshot::from_path_stats(digester.clone(), vec![file])
        .await
        .unwrap();

    let merged_res = store
        .merge(vec![snapshot1.clone().into(), snapshot1_cloned.into()])
        .await;

    assert_eq!(merged_res, Ok(snapshot1.into()));
}

#[tokio::test]
async fn snapshot_merge_colliding() {
    let (store, tempdir, posix_fs, digester) = setup();

    make_file(&tempdir.path().join("roland"), STR.as_bytes(), 0o600);
    let path_stats1 = expand_all_sorted(posix_fs).await;
    let snapshot1 = Snapshot::from_path_stats(digester.clone(), path_stats1)
        .await
        .unwrap();

    // When the file is *not* the same, error out.
    let (_store2, tempdir2, posix_fs2, digester2) = setup();
    make_file(&tempdir2.path().join("roland"), STR2.as_bytes(), 0o600);
    let path_stats2 = expand_all_sorted(posix_fs2).await;
    let snapshot2 = Snapshot::from_path_stats(digester2, path_stats2)
        .await
        .unwrap();

    let merged_res = store.merge(vec![snapshot1.into(), snapshot2.into()]).await;

    match merged_res {
        Err(ref msg)
            if format!("{msg:?}").contains("found 2 duplicate entries")
                && format!("{msg:?}").contains("roland") => {}
        x => panic!("Snapshot::merge should have failed with a useful message; got: {x:?}"),
    }
}

#[tokio::test]
async fn strip_empty_and_non_empty_prefix() {
    let (store, _, _, _) = setup();

    let dir = TestDirectory::nested();
    store
        .record_directory(&dir.directory(), false)
        .await
        .expect("Error storing directory");
    store
        .record_directory(&TestDirectory::containing_roland().directory(), false)
        .await
        .expect("Error storing directory");

    // Empty.
    let prefix = RelativePath::new(PathBuf::from("")).unwrap();
    let result = store.strip_prefix(dir.directory_digest(), &prefix).await;
    assert_eq!(result, Ok(dir.directory_digest()));

    // Non-empty.
    let prefix = RelativePath::new(PathBuf::from("cats")).unwrap();
    let result = store.strip_prefix(dir.directory_digest(), &prefix).await;
    assert_eq!(
        result,
        Ok(TestDirectory::containing_roland().directory_digest())
    );
}

#[tokio::test]
async fn strip_prefix_empty_subdir() {
    let (store, _, _, _) = setup();

    let dir = TestDirectory::containing_falcons_dir();
    store
        .record_directory(&dir.directory(), false)
        .await
        .expect("Error storing directory");

    let prefix = RelativePath::new(PathBuf::from("falcons/peregrine")).unwrap();
    let result = store.strip_prefix(dir.directory_digest(), &prefix).await;
    assert_eq!(result, Ok(TestDirectory::empty().directory_digest()));
}

#[tokio::test]
async fn strip_dir_not_in_store() {
    let (store, _, _, _) = setup();
    let digest = TestDirectory::nested().directory_digest();
    let prefix = RelativePath::new(PathBuf::from("cats")).unwrap();
    let result = store.strip_prefix(digest.clone(), &prefix).await;
    assert!(matches!(result, Err(StoreError::MissingDigest { .. })),);
}

#[tokio::test]
async fn strip_prefix_non_matching_file() {
    let (store, _, _, _) = setup();
    let dir = TestDirectory::recursive();
    let child_dir = TestDirectory::containing_roland();
    store
        .record_directory(&dir.directory(), false)
        .await
        .expect("Error storing directory");
    store
        .record_directory(&child_dir.directory(), false)
        .await
        .expect("Error storing directory");
    let prefix = RelativePath::new(PathBuf::from("cats")).unwrap();
    let result = store.strip_prefix(dir.directory_digest(), &prefix).await;

    assert_eq!(
        result,
        Err(format!(
            "Cannot strip prefix cats from root directory (Digest with hash {:?}) - \
         root directory contained non-matching file named: treats.ext",
            dir.digest().hash
        )
        .into())
    );
}

#[tokio::test]
async fn strip_prefix_non_matching_dir() {
    let (store, _, _, _) = setup();
    let dir = TestDirectory::double_nested_dir_and_file();
    store
        .record_directory(&dir.directory(), false)
        .await
        .expect("Error storing directory");
    store
        .record_directory(&TestDirectory::nested_dir_and_file().directory(), false)
        .await
        .expect("Error storing directory");
    store
        .record_directory(&TestDirectory::containing_falcons_dir().directory(), false)
        .await
        .expect("Error storing directory");
    store
        .record_directory(&TestDirectory::containing_roland().directory(), false)
        .await
        .expect("Error storing directory");
    let prefix = RelativePath::new(PathBuf::from("animals/cats")).unwrap();
    let result = store.strip_prefix(dir.directory_digest(), &prefix).await;

    assert_eq!(
        result,
        Err(format!(
            "Cannot strip prefix animals/cats from root directory (Digest with hash {:?}) - \
         subdirectory animals contained non-matching directory named: birds",
            dir.digest().hash
        )
        .into())
    );
}

#[tokio::test]
async fn strip_subdir_not_in_dir() {
    let (store, _, _, _) = setup();
    let dir = TestDirectory::nested();
    store
        .record_directory(&dir.directory(), false)
        .await
        .expect("Error storing directory");
    store
        .record_directory(&TestDirectory::containing_roland().directory(), false)
        .await
        .expect("Error storing directory");
    let prefix = RelativePath::new(PathBuf::from("cats/ugly")).unwrap();
    let result = store.strip_prefix(dir.directory_digest(), &prefix).await;
    assert_eq!(
        result,
        Err(format!(
            "Cannot strip prefix cats/ugly from root directory (Digest with hash {:?}) - \
         subdirectory cats didn't contain a directory named ugly \
         but did contain file named: roland.ext",
            dir.digest().hash
        )
        .into())
    );
}

fn make_dir_stat(root: &Path, relpath: &Path) -> PathStat {
    std::fs::create_dir(root.join(relpath)).unwrap();
    PathStat::dir(relpath.to_owned(), Dir(relpath.to_owned()))
}

fn make_file_stat(root: &Path, relpath: &Path, contents: &[u8], is_executable: bool) -> PathStat {
    make_file(
        &root.join(relpath),
        contents,
        if is_executable { 0o555 } else { 0o444 },
    );
    PathStat::file(
        relpath.to_owned(),
        File {
            path: relpath.to_owned(),
            is_executable,
        },
    )
}

pub async fn expand_all_sorted(posix_fs: Arc<PosixFS>) -> Vec<PathStat> {
    let path_globs = PathGlobs::new(
        vec!["**".to_owned()],
        // Don't error or warn if there are no paths matched -- that is a valid state.
        StrictGlobMatching::Ignore,
        GlobExpansionConjunction::AllMatch,
    )
    .parse()
    .unwrap();
    let mut v = posix_fs
        .expand_globs(path_globs, SymlinkBehavior::Aware, None)
        .await
        .unwrap();
    v.sort_by(|a, b| a.path().cmp(b.path()));
    v
}
