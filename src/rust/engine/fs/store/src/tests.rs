// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};

use bytes::Bytes;
use fs::{
    DigestEntry, DirectoryDigest, FileEntry, Link, PathStat, Permissions, RelativePath,
    EMPTY_DIRECTORY_DIGEST,
};
use grpc_util::prost::MessageExt;
use grpc_util::tls;
use hashing::Digest;
use mock::{RequestType, StubCAS};
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use workunit_store::WorkunitStore;

use crate::local::ByteStore;
use crate::{
    EntryType, FileContent, RemoteStoreOptions, Snapshot, Store, StoreError, StoreFileByDigest,
    UploadSummary, MEGABYTES,
};

pub(crate) const STORE_BATCH_API_SIZE_LIMIT: usize = 4 * 1024 * 1024;

pub async fn load_file_bytes(store: &Store, digest: Digest) -> Result<Bytes, StoreError> {
    store
        .load_file_bytes_with(digest, Bytes::copy_from_slice)
        .await
}

///
/// Create a StubCas with a file and a directory inside.
///
pub fn new_cas(chunk_size_bytes: usize) -> StubCAS {
    let _ = WorkunitStore::setup_for_tests();
    StubCAS::builder()
        .chunk_size_bytes(chunk_size_bytes)
        .file(&TestData::roland())
        .directory(&TestDirectory::containing_roland())
        .build()
}

pub fn new_empty_cas() -> StubCAS {
    let _ = WorkunitStore::setup_for_tests();
    StubCAS::empty()
}

///
/// Create a new local store with whatever was already serialized in dir.
///
fn new_local_store<P: AsRef<Path>>(dir: P) -> Store {
    Store::local_only(task_executor::Executor::new(), dir).expect("Error creating local store")
}

fn remote_options(
    store_address: String,
    instance_name: Option<String>,
    headers: BTreeMap<String, String>,
) -> RemoteStoreOptions {
    RemoteStoreOptions {
        store_address,
        instance_name,
        tls_config: tls::Config::default(),
        headers,
        chunk_size_bytes: 10 * MEGABYTES,
        timeout: Duration::from_secs(1),
        retries: 1,
        concurrency_limit: 256,
        batch_api_size_limit: STORE_BATCH_API_SIZE_LIMIT,
    }
}
///
/// Create a new store with a remote CAS.
///
async fn new_store<P: AsRef<Path>>(dir: P, cas_address: &str) -> Store {
    Store::local_only(task_executor::Executor::new(), dir)
        .unwrap()
        .into_with_remote(remote_options(
            cas_address.to_owned(),
            None,
            BTreeMap::new(),
        ))
        .await
        .unwrap()
}

#[tokio::test]
async fn load_file_prefers_local() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    crate::local_tests::new_store(dir.path())
        .store_bytes(
            EntryType::File,
            testdata.fingerprint(),
            testdata.bytes(),
            false,
        )
        .await
        .expect("Store failed");

    let cas = new_cas(1024);
    assert_eq!(
        load_file_bytes(
            &new_store(dir.path(), &cas.address()).await,
            testdata.digest()
        )
        .await,
        Ok(testdata.bytes())
    );
    assert_eq!(0, cas.request_count(RequestType::BSRead));
}

#[tokio::test]
async fn load_directory_prefers_local() {
    let dir = TempDir::new().unwrap();

    let testdir = TestDirectory::containing_roland();

    crate::local_tests::new_store(dir.path())
        .store_bytes(
            EntryType::Directory,
            testdir.fingerprint(),
            testdir.bytes(),
            false,
        )
        .await
        .expect("Store failed");

    let cas = new_cas(1024);
    assert_eq!(
        new_store(dir.path(), &cas.address())
            .await
            .load_directory(testdir.digest(),)
            .await
            .unwrap(),
        testdir.directory()
    );
    assert_eq!(0, cas.request_count(RequestType::BSRead));
}

#[tokio::test]
async fn load_file_falls_back_and_backfills() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    let cas = new_cas(1024);
    assert_eq!(
        load_file_bytes(
            &new_store(dir.path(), &cas.address()).await,
            testdata.digest()
        )
        .await,
        Ok(testdata.bytes()),
        "Read from CAS"
    );
    assert_eq!(1, cas.request_count(RequestType::BSRead));
    assert_eq!(
        crate::local_tests::load_file_bytes(
            &crate::local_tests::new_store(dir.path()),
            testdata.digest(),
        )
        .await,
        Ok(Some(testdata.bytes())),
        "Read from local cache"
    );
}

#[tokio::test]
async fn load_file_falls_back_and_backfills_for_huge_file() {
    let dir = TempDir::new().unwrap();

    // 5MB of data
    let testdata = TestData::new(&"12345".repeat(MEGABYTES));

    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder()
        .chunk_size_bytes(MEGABYTES)
        .file(&testdata)
        .build();

    assert_eq!(
        load_file_bytes(
            &new_store(dir.path(), &cas.address()).await,
            testdata.digest()
        )
        .await
        .unwrap(),
        testdata.bytes()
    );
    assert_eq!(1, cas.request_count(RequestType::BSRead));
    assert!(
        crate::local_tests::load_file_bytes(
            &crate::local_tests::new_store(dir.path()),
            testdata.digest(),
        )
        .await
            == Ok(Some(testdata.bytes())),
        "Read from local cache"
    );
}

#[tokio::test]
async fn load_directory_small_falls_back_and_backfills() {
    let dir = TempDir::new().unwrap();

    let cas = new_cas(1024);

    let testdir = TestDirectory::containing_roland();

    assert_eq!(
        new_store(dir.path(), &cas.address())
            .await
            .load_directory(testdir.digest(),)
            .await
            .unwrap(),
        testdir.directory()
    );
    assert_eq!(1, cas.request_count(RequestType::BSRead));
    assert_eq!(
        crate::local_tests::load_directory_proto_bytes(
            &crate::local_tests::new_store(dir.path()),
            testdir.digest(),
        )
        .await,
        Ok(Some(testdir.bytes()))
    );
}

#[tokio::test]
async fn load_directory_huge_falls_back_and_backfills() {
    let dir = TempDir::new().unwrap();

    let testdir = TestDirectory::many_files();
    let digest = testdir.digest();
    // this test is ensuring that "huge" directories don't fall into the FSDB code paths, so let's
    // ensure we're actually testing that, by validating that a _file_ of this size would use FSDB
    assert!(ByteStore::should_use_fsdb(
        EntryType::File,
        digest.size_bytes
    ));

    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder()
        .directory(&testdir)
        .file(&TestData::empty())
        .build();

    assert_eq!(
        new_store(dir.path(), &cas.address())
            .await
            .load_directory(digest)
            .await
            .unwrap(),
        testdir.directory()
    );
    assert_eq!(1, cas.request_count(RequestType::BSRead));
    assert_eq!(
        crate::local_tests::load_directory_proto_bytes(
            &crate::local_tests::new_store(dir.path()),
            testdir.digest(),
        )
        .await,
        Ok(Some(testdir.bytes()))
    );
}

#[tokio::test]
async fn load_recursive_directory() {
    let dir = TempDir::new().unwrap();

    let roland = TestData::roland();
    let catnip = TestData::catnip();
    let testdir = TestDirectory::containing_roland();
    let testdir_digest = testdir.digest();
    let testdir_directory = testdir.directory();
    let recursive_testdir = TestDirectory::recursive();
    let recursive_testdir_directory = recursive_testdir.directory();
    let recursive_testdir_digest = recursive_testdir.directory_digest();

    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder()
        .file(&roland)
        .file(&catnip)
        .directory(&testdir)
        .directory(&recursive_testdir)
        .build();

    new_store(dir.path(), &cas.address())
        .await
        .ensure_downloaded(
            HashSet::new(),
            HashSet::from([recursive_testdir_digest.clone()]),
        )
        .await
        .expect("Downloading recursive directory should have succeeded.");

    assert_eq!(
        load_file_bytes(&new_local_store(dir.path()), roland.digest()).await,
        Ok(roland.bytes())
    );
    assert_eq!(
        load_file_bytes(&new_local_store(dir.path()), catnip.digest()).await,
        Ok(catnip.bytes())
    );
    assert_eq!(
        new_local_store(dir.path())
            .load_directory(testdir_digest,)
            .await
            .unwrap(),
        testdir_directory
    );
    assert_eq!(
        new_local_store(dir.path())
            .load_directory(recursive_testdir_digest.as_digest())
            .await
            .unwrap(),
        recursive_testdir_directory
    );
}

#[tokio::test]
async fn load_file_missing_is_none() {
    let dir = TempDir::new().unwrap();

    let cas = new_empty_cas();
    let result = load_file_bytes(
        &new_store(dir.path(), &cas.address()).await,
        TestData::roland().digest(),
    )
    .await;
    assert!(matches!(result, Err(StoreError::MissingDigest { .. })),);
    assert_eq!(1, cas.request_count(RequestType::BSRead));
}

#[tokio::test]
async fn load_directory_missing_errors() {
    let dir = TempDir::new().unwrap();

    let cas = new_empty_cas();
    let result = new_store(dir.path(), &cas.address())
        .await
        .load_directory(TestDirectory::containing_roland().digest())
        .await;
    assert!(matches!(result, Err(StoreError::MissingDigest { .. })),);
    assert_eq!(1, cas.request_count(RequestType::BSRead));
}

#[tokio::test]
async fn load_file_remote_error_is_error() {
    let dir = TempDir::new().unwrap();

    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::cas_always_errors();
    let error = load_file_bytes(
        &new_store(dir.path(), &cas.address()).await,
        TestData::roland().digest(),
    )
    .await
    .expect_err("Want error");
    assert!(
        cas.request_count(RequestType::BSRead) > 0,
        "Want read_request_count > 0 but got {}",
        cas.request_count(RequestType::BSRead)
    );
    assert!(
        error
            .to_string()
            .contains("StubCAS is configured to always fail"),
        "Bad error message"
    );
}

#[tokio::test]
async fn load_directory_remote_error_is_error() {
    let dir = TempDir::new().unwrap();

    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::cas_always_errors();
    let error = new_store(dir.path(), &cas.address())
        .await
        .load_directory(TestData::roland().digest())
        .await
        .expect_err("Want error");
    assert!(
        cas.request_count(RequestType::BSRead) > 0,
        "Want read_request_count > 0 but got {}",
        cas.request_count(RequestType::BSRead)
    );
    assert!(
        error
            .to_string()
            .contains("StubCAS is configured to always fail"),
        "Bad error message"
    );
}

#[tokio::test]
async fn roundtrip_symlink() {
    let _ = WorkunitStore::setup_for_tests();
    let dir = TempDir::new().unwrap();

    #[derive(Clone)]
    struct NoopDigester;

    impl StoreFileByDigest<String> for NoopDigester {
        fn store_by_digest(
            &self,
            _: fs::File,
        ) -> futures::future::BoxFuture<'static, Result<hashing::Digest, String>> {
            unimplemented!();
        }
    }

    let input_digest: DirectoryDigest = Snapshot::from_path_stats(
        NoopDigester,
        vec![PathStat::link(
            "x".into(),
            Link {
                path: "x".into(),
                target: "y".into(),
            },
        )],
    )
    .await
    .unwrap()
    .into();

    let store = new_local_store(dir.path());

    store
        .ensure_directory_digest_persisted(input_digest.clone())
        .await
        .unwrap();

    // Discard the DigestTrie to force it to be reloaded from disk.
    let digest = DirectoryDigest::from_persisted_digest(input_digest.as_digest());
    assert!(digest.tree.is_none());

    let output_digest: DirectoryDigest = store.load_digest_trie(digest).await.unwrap().into();
    assert_eq!(input_digest.as_digest(), output_digest.as_digest());
}

#[tokio::test]
async fn malformed_remote_directory_is_error() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    let cas = new_cas(1024);
    new_store(dir.path(), &cas.address())
        .await
        .load_directory(testdata.digest())
        .await
        .expect_err("Want error");

    assert_eq!(
        crate::local_tests::load_directory_proto_bytes(
            &crate::local_tests::new_store(dir.path()),
            testdata.digest()
        )
        .await,
        Ok(None)
    );
}

#[tokio::test]
async fn non_canonical_remote_directory_is_error() {
    let mut non_canonical_directory = TestDirectory::containing_roland().directory();
    non_canonical_directory.files.push({
        remexec::FileNode {
            name: "roland".to_string(),
            digest: Some((&TestData::roland().digest()).into()),
            ..Default::default()
        }
    });
    let non_canonical_directory_bytes = non_canonical_directory.to_bytes();
    let directory_digest = Digest::of_bytes(&non_canonical_directory_bytes);
    let non_canonical_directory_fingerprint = directory_digest.hash;

    let dir = TempDir::new().unwrap();

    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder()
        .unverified_content(
            non_canonical_directory_fingerprint,
            non_canonical_directory_bytes,
        )
        .build();
    new_store(dir.path(), &cas.address())
        .await
        .load_directory(directory_digest)
        .await
        .expect_err("Want error");

    assert_eq!(
        crate::local_tests::load_directory_proto_bytes(
            &crate::local_tests::new_store(dir.path()),
            directory_digest,
        )
        .await,
        Ok(None)
    );
}

#[tokio::test]
async fn wrong_remote_file_bytes_is_error() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder()
        .unverified_content(
            testdata.fingerprint(),
            TestDirectory::containing_roland().bytes(),
        )
        .build();
    load_file_bytes(
        &new_store(dir.path(), &cas.address()).await,
        testdata.digest(),
    )
    .await
    .expect_err("Want error");

    assert_eq!(
        crate::local_tests::load_file_bytes(
            &crate::local_tests::new_store(dir.path()),
            testdata.digest()
        )
        .await,
        Ok(None)
    );
}

#[tokio::test]
async fn wrong_remote_directory_bytes_is_error() {
    let dir = TempDir::new().unwrap();

    let testdir = TestDirectory::containing_dnalor();

    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder()
        .unverified_content(
            testdir.fingerprint(),
            TestDirectory::containing_roland().bytes(),
        )
        .build();
    load_file_bytes(
        &new_store(dir.path(), &cas.address()).await,
        testdir.digest(),
    )
    .await
    .expect_err("Want error");

    assert_eq!(
        crate::local_tests::load_file_bytes(
            &crate::local_tests::new_store(dir.path()),
            testdir.digest()
        )
        .await,
        Ok(None)
    );
}

#[tokio::test]
async fn expand_empty_directory() {
    let dir = TempDir::new().unwrap();

    let empty_dir = TestDirectory::empty();

    let expanded = new_local_store(dir.path())
        .expand_directory(empty_dir.digest())
        .await
        .expect("Error expanding directory");
    let want: HashMap<Digest, EntryType> = vec![(empty_dir.digest(), EntryType::Directory)]
        .into_iter()
        .collect();
    assert_eq!(expanded, want);
}

#[tokio::test]
async fn expand_flat_directory() {
    let dir = TempDir::new().unwrap();

    let roland = TestData::roland();
    let testdir = TestDirectory::containing_roland();

    new_local_store(dir.path())
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error storing directory locally");

    let expanded = new_local_store(dir.path())
        .expand_directory(testdir.digest())
        .await
        .expect("Error expanding directory");
    let want: HashMap<Digest, EntryType> = vec![
        (testdir.digest(), EntryType::Directory),
        (roland.digest(), EntryType::File),
    ]
    .into_iter()
    .collect();
    assert_eq!(expanded, want);
}

#[tokio::test]
async fn expand_recursive_directory() {
    let dir = TempDir::new().unwrap();

    let roland = TestData::roland();
    let catnip = TestData::catnip();
    let testdir = TestDirectory::containing_roland();
    let recursive_testdir = TestDirectory::recursive();

    new_local_store(dir.path())
        .record_directory(&recursive_testdir.directory(), false)
        .await
        .expect("Error storing directory locally");
    new_local_store(dir.path())
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error storing directory locally");

    let expanded = new_local_store(dir.path())
        .expand_directory(recursive_testdir.digest())
        .await
        .expect("Error expanding directory");
    let want: HashMap<Digest, EntryType> = vec![
        (recursive_testdir.digest(), EntryType::Directory),
        (testdir.digest(), EntryType::Directory),
        (roland.digest(), EntryType::File),
        (catnip.digest(), EntryType::File),
    ]
    .into_iter()
    .collect();
    assert_eq!(expanded, want);
}

#[tokio::test]
async fn expand_missing_directory() {
    let dir = TempDir::new().unwrap();
    let digest = TestDirectory::containing_roland().digest();
    let error = new_local_store(dir.path())
        .expand_directory(digest)
        .await
        .expect_err("Want error");
    assert!(
        matches!(error, StoreError::MissingDigest { .. }),
        "Bad error: {error}"
    );
}

#[tokio::test]
async fn expand_directory_missing_subdir() {
    let dir = TempDir::new().unwrap();

    let recursive_testdir = TestDirectory::recursive();

    new_local_store(dir.path())
        .record_directory(&recursive_testdir.directory(), false)
        .await
        .expect("Error storing directory locally");

    let error = new_local_store(dir.path())
        .expand_directory(recursive_testdir.digest())
        .await
        .expect_err("Want error");
    assert!(
        matches!(error, StoreError::MissingDigest { .. }),
        "Bad error message: {error}"
    );
}

#[tokio::test]
async fn uploads_files() {
    let dir = TempDir::new().unwrap();
    let cas = new_empty_cas();

    let testdata = TestData::roland();

    new_local_store(dir.path())
        .store_file_bytes(testdata.bytes(), false)
        .await
        .expect("Error storing file locally");

    assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);

    new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testdata.digest()])
        .await
        .expect("Error uploading file");

    assert_eq!(
        cas.blobs.lock().get(&testdata.fingerprint()),
        Some(&testdata.bytes())
    );
}

#[tokio::test]
async fn uploads_directories_recursively() {
    let dir = TempDir::new().unwrap();
    let cas = new_empty_cas();

    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();

    new_local_store(dir.path())
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error storing directory locally");
    new_local_store(dir.path())
        .store_file_bytes(testdata.bytes(), false)
        .await
        .expect("Error storing file locally");

    assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);
    assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);

    new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testdir.digest()])
        .await
        .expect("Error uploading directory");

    assert_eq!(
        cas.blobs.lock().get(&testdir.fingerprint()),
        Some(&testdir.bytes())
    );
    assert_eq!(
        cas.blobs.lock().get(&testdata.fingerprint()),
        Some(&testdata.bytes())
    );
}

#[tokio::test]
async fn uploads_files_recursively_when_under_three_digests_ignoring_items_already_in_cas() {
    let dir = TempDir::new().unwrap();
    let cas = new_empty_cas();

    let testdata = TestData::roland();
    let testdir = TestDirectory::containing_roland();

    new_local_store(dir.path())
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error storing directory locally");
    new_local_store(dir.path())
        .store_file_bytes(testdata.bytes(), false)
        .await
        .expect("Error storing file locally");

    new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testdata.digest()])
        .await
        .expect("Error uploading file");

    assert_eq!(cas.write_message_sizes.lock().len(), 1);
    assert_eq!(
        cas.blobs.lock().get(&testdata.fingerprint()),
        Some(&testdata.bytes())
    );
    assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);

    new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testdir.digest()])
        .await
        .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().len(), 3);
    assert_eq!(
        cas.blobs.lock().get(&testdir.fingerprint()),
        Some(&testdir.bytes())
    );
}

#[tokio::test]
async fn does_not_reupload_file_already_in_cas_when_requested_with_three_other_digests() {
    let dir = TempDir::new().unwrap();
    let cas = new_empty_cas();

    let catnip = TestData::catnip();
    let roland = TestData::roland();
    let testdir = TestDirectory::containing_roland();

    new_local_store(dir.path())
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error storing directory locally");
    new_local_store(dir.path())
        .store_file_bytes(roland.bytes(), false)
        .await
        .expect("Error storing file locally");
    new_local_store(dir.path())
        .store_file_bytes(catnip.bytes(), false)
        .await
        .expect("Error storing file locally");

    new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![roland.digest()])
        .await
        .expect("Error uploading big file");

    assert_eq!(cas.write_message_sizes.lock().len(), 1);
    assert_eq!(
        cas.blobs.lock().get(&roland.fingerprint()),
        Some(&roland.bytes())
    );
    assert_eq!(cas.blobs.lock().get(&catnip.fingerprint()), None);
    assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);

    new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testdir.digest(), catnip.digest()])
        .await
        .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().len(), 3);
    assert_eq!(
        cas.blobs.lock().get(&catnip.fingerprint()),
        Some(&catnip.bytes())
    );
    assert_eq!(
        cas.blobs.lock().get(&testdir.fingerprint()),
        Some(&testdir.bytes())
    );
}

#[tokio::test]
async fn does_not_reupload_big_file_already_in_cas() {
    let dir = TempDir::new().unwrap();
    let cas = new_empty_cas();

    let testdata = TestData::double_all_the_henries();

    new_local_store(dir.path())
        .store_file_bytes(testdata.bytes(), false)
        .await
        .expect("Error storing file locally");

    new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testdata.digest()])
        .await
        .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().len(), 1);
    assert_eq!(
        cas.blobs.lock().get(&testdata.fingerprint()),
        Some(&testdata.bytes())
    );

    new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testdata.digest()])
        .await
        .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().len(), 1);
    assert_eq!(
        cas.blobs.lock().get(&testdata.fingerprint()),
        Some(&testdata.bytes())
    );
}

#[tokio::test]
async fn upload_missing_files() {
    let dir = TempDir::new().unwrap();
    let cas = new_empty_cas();

    let testdata = TestData::roland();

    assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);

    let error = new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testdata.digest()])
        .await
        .expect_err("Want error");
    assert!(
        matches!(error, StoreError::MissingDigest { .. }),
        "Bad error: {error}"
    );
}

#[tokio::test]
async fn upload_succeeds_for_digests_which_only_exist_remotely() {
    let dir = TempDir::new().unwrap();
    let cas = new_empty_cas();

    let testdata = TestData::roland();

    cas.blobs
        .lock()
        .insert(testdata.fingerprint(), testdata.bytes());

    // The data does not exist locally, but already exists remotely: succeed.
    new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testdata.digest()])
        .await
        .unwrap();
}

#[tokio::test]
async fn upload_missing_file_in_directory() {
    let dir = TempDir::new().unwrap();
    let cas = new_empty_cas();

    let testdir = TestDirectory::containing_roland();

    new_local_store(dir.path())
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error storing directory locally");

    assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);
    assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);

    let error = new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testdir.digest()])
        .await
        .expect_err("Want error");
    assert!(
        matches!(error, StoreError::MissingDigest { .. }),
        "Bad error: {error}"
    );
}

#[tokio::test]
async fn uploading_digest_with_wrong_size_is_error() {
    let dir = TempDir::new().unwrap();
    let cas = new_empty_cas();

    let testdata = TestData::roland();

    new_local_store(dir.path())
        .store_file_bytes(testdata.bytes(), false)
        .await
        .expect("Error storing file locally");

    assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);

    let wrong_digest = Digest::new(testdata.fingerprint(), testdata.len() + 1);

    new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![wrong_digest])
        .await
        .expect_err("Expect error uploading file");

    assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);
}

#[tokio::test]
async fn instance_name_upload() {
    let dir = TempDir::new().unwrap();
    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder()
        .instance_name("dark-tower".to_owned())
        .build();

    // 3 is enough digests to trigger a FindMissingBlobs request
    let testdir = TestDirectory::containing_roland_and_treats();

    new_local_store(dir.path())
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error storing directory locally");
    new_local_store(dir.path())
        .store_file_bytes(TestData::roland().bytes(), false)
        .await
        .expect("Error storing roland locally");
    new_local_store(dir.path())
        .store_file_bytes(TestData::catnip().bytes(), false)
        .await
        .expect("Error storing catnip locally");

    let store_with_remote = Store::local_only(task_executor::Executor::new(), dir.path())
        .unwrap()
        .into_with_remote(remote_options(
            cas.address(),
            Some("dark-tower".to_owned()),
            BTreeMap::new(),
        ))
        .await
        .unwrap();

    store_with_remote
        .ensure_remote_has_recursive(vec![testdir.digest()])
        .await
        .expect("Error uploading");
}

#[tokio::test]
async fn instance_name_download() {
    let dir = TempDir::new().unwrap();
    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder()
        .instance_name("dark-tower".to_owned())
        .file(&TestData::roland())
        .build();

    let store_with_remote = Store::local_only(task_executor::Executor::new(), dir.path())
        .unwrap()
        .into_with_remote(remote_options(
            cas.address(),
            Some("dark-tower".to_owned()),
            BTreeMap::new(),
        ))
        .await
        .unwrap();

    assert_eq!(
        store_with_remote
            .load_file_bytes_with(TestData::roland().digest(), Bytes::copy_from_slice)
            .await
            .unwrap(),
        TestData::roland().bytes()
    )
}

#[tokio::test]
async fn auth_upload() {
    let dir = TempDir::new().unwrap();
    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder()
        .required_auth_token("Armory.Key".to_owned())
        .build();

    // 3 is enough digests to trigger a FindMissingBlobs request
    let testdir = TestDirectory::containing_roland_and_treats();

    new_local_store(dir.path())
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error storing directory locally");
    new_local_store(dir.path())
        .store_file_bytes(TestData::roland().bytes(), false)
        .await
        .expect("Error storing roland locally");
    new_local_store(dir.path())
        .store_file_bytes(TestData::catnip().bytes(), false)
        .await
        .expect("Error storing catnip locally");

    let mut headers = BTreeMap::new();
    headers.insert("authorization".to_owned(), "Bearer Armory.Key".to_owned());
    let store_with_remote = Store::local_only(task_executor::Executor::new(), dir.path())
        .unwrap()
        .into_with_remote(remote_options(cas.address(), None, headers))
        .await
        .unwrap();

    store_with_remote
        .ensure_remote_has_recursive(vec![testdir.digest()])
        .await
        .expect("Error uploading");
}

#[tokio::test]
async fn auth_download() {
    let dir = TempDir::new().unwrap();
    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder()
        .required_auth_token("Armory.Key".to_owned())
        .file(&TestData::roland())
        .build();

    let mut headers = BTreeMap::new();
    headers.insert("authorization".to_owned(), "Bearer Armory.Key".to_owned());
    let store_with_remote = Store::local_only(task_executor::Executor::new(), dir.path())
        .unwrap()
        .into_with_remote(remote_options(cas.address(), None, headers))
        .await
        .unwrap();

    assert_eq!(
        store_with_remote
            .load_file_bytes_with(TestData::roland().digest(), Bytes::copy_from_slice)
            .await
            .unwrap(),
        TestData::roland().bytes()
    )
}

#[tokio::test]
async fn materialize_missing_file() {
    let materialize_dir = TempDir::new().unwrap();
    let file = materialize_dir.path().join("file");

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
        .materialize_file(
            file.clone(),
            TestData::roland().digest(),
            Permissions::ReadOnly,
            false,
        )
        .await
        .expect_err("Want unknown digest error");
}

#[tokio::test]
async fn materialize_file() {
    let materialize_dir = TempDir::new().unwrap();
    let file = materialize_dir.path().join("file");

    let testdata = TestData::roland();

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
        .store_file_bytes(testdata.bytes(), false)
        .await
        .expect("Error saving bytes");
    store
        .materialize_file(
            file.clone(),
            testdata.digest(),
            Permissions::ReadOnly,
            false,
        )
        .await
        .expect("Error materializing file");
    assert_eq!(file_contents(&file), testdata.bytes());
    assert!(!is_executable(&file));
}

#[tokio::test]
async fn materialize_missing_directory() {
    let materialize_dir = TempDir::new().unwrap();

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
        .materialize_directory(
            materialize_dir.path().to_owned(),
            materialize_dir.path(),
            TestDirectory::recursive().directory_digest(),
            false,
            &BTreeSet::new(),
            Permissions::Writable,
        )
        .await
        .expect_err("Want unknown digest error");
}

async fn materialize_directory(perms: Permissions, executable_file: bool) {
    let materialize_dir = TempDir::new().unwrap();

    let catnip = TestData::catnip();
    let testdir = TestDirectory::with_maybe_executable_files(executable_file);
    let recursive_testdir = TestDirectory::recursive_with(testdir.clone());

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
        .record_directory(&recursive_testdir.directory(), false)
        .await
        .expect("Error saving recursive Directory");
    store
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error saving Directory");
    store
        .store_file_bytes(catnip.bytes(), false)
        .await
        .expect("Error saving file bytes");

    store
        .materialize_directory(
            materialize_dir.path().to_owned(),
            materialize_dir.path(),
            recursive_testdir.directory_digest(),
            false,
            &BTreeSet::new(),
            perms,
        )
        .await
        .expect("Error materializing");

    // Validate contents.
    assert_eq!(list_dir(materialize_dir.path()), vec!["cats", "treats.ext"]);
    assert_eq!(
        file_contents(&materialize_dir.path().join("treats.ext")),
        catnip.bytes()
    );
    assert_eq!(
        list_dir(&materialize_dir.path().join("cats")),
        vec!["feed.ext", "food.ext"]
    );
    assert_eq!(
        file_contents(&materialize_dir.path().join("cats").join("feed.ext")),
        catnip.bytes()
    );

    // Validate executability.
    assert_eq!(
        executable_file,
        is_executable(&materialize_dir.path().join("cats").join("feed.ext"))
    );
    assert!(!is_executable(
        &materialize_dir.path().join("cats").join("food.ext")
    ));

    // Validate read/write permissions for a file, a nested directory, and the root.
    let readonly = perms == Permissions::ReadOnly;
    assert_eq!(
        readonly,
        is_readonly(&materialize_dir.path().join("cats").join("feed.ext"))
    );
    assert_eq!(readonly, is_readonly(&materialize_dir.path().join("cats")));
    assert_eq!(readonly, is_readonly(materialize_dir.path()));
}

#[tokio::test]
async fn materialize_directory_writable() {
    materialize_directory(Permissions::Writable, false).await
}

#[tokio::test]
async fn materialize_directory_writable_executable() {
    materialize_directory(Permissions::Writable, true).await
}

#[tokio::test]
async fn materialize_directory_readonly() {
    materialize_directory(Permissions::ReadOnly, false).await
}

#[tokio::test]
async fn materialize_directory_readonly_executable() {
    materialize_directory(Permissions::Writable, true).await
}

#[tokio::test]
async fn contents_for_directory_empty() {
    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());

    let file_contents = store
        .contents_for_directory(TestDirectory::empty().directory_digest())
        .await
        .expect("Getting FileContents");

    assert_same_filecontents(file_contents, vec![]);
}

#[tokio::test]
async fn contents_for_directory() {
    let roland = TestData::roland();
    let catnip = TestData::catnip();
    let testdir = TestDirectory::containing_roland();
    let recursive_testdir = TestDirectory::recursive();

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
        .record_directory(&recursive_testdir.directory(), false)
        .await
        .expect("Error saving recursive Directory");
    store
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error saving Directory");
    store
        .store_file_bytes(roland.bytes(), false)
        .await
        .expect("Error saving file bytes");
    store
        .store_file_bytes(catnip.bytes(), false)
        .await
        .expect("Error saving catnip file bytes");

    let file_contents = store
        .contents_for_directory(recursive_testdir.directory_digest())
        .await
        .expect("Getting FileContents");

    assert_same_filecontents(
        file_contents,
        vec![
            FileContent {
                path: PathBuf::from("cats").join("roland.ext"),
                content: roland.bytes(),
                is_executable: false,
            },
            FileContent {
                path: PathBuf::from("treats.ext"),
                content: catnip.bytes(),
                is_executable: false,
            },
        ],
    );
}

fn assert_same_filecontents(left: Vec<FileContent>, right: Vec<FileContent>) {
    assert_eq!(
        left.len(),
        right.len(),
        "FileContents did not match, different lengths: left: {left:?} right: {right:?}"
    );

    let mut success = true;
    for (index, (l, r)) in left.iter().zip(right.iter()).enumerate() {
        if l.path != r.path {
            success = false;
            eprintln!(
                "Paths did not match for index {}: {:?}, {:?}",
                index, l.path, r.path
            );
        }
        if l.content != r.content {
            success = false;
            eprintln!(
                "Content did not match for index {}: {:?}, {:?}",
                index, l.content, r.content
            );
        }
        if l.is_executable != r.is_executable {
            success = false;
            eprintln!(
                "Executable bit did not match for index {}: {:?}, {:?}",
                index, l.is_executable, r.is_executable
            );
        }
    }
    assert!(
        success,
        "FileContents did not match: Left: {left:?}, Right: {right:?}"
    );
}

#[tokio::test]
async fn entries_for_directory() {
    let roland = TestData::roland();
    let catnip = TestData::catnip();
    let testdir = TestDirectory::containing_roland();
    let recursive_testdir = TestDirectory::recursive();

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
        .record_directory(&recursive_testdir.directory(), false)
        .await
        .expect("Error saving recursive Directory");
    store
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error saving Directory");
    store
        .store_file_bytes(roland.bytes(), false)
        .await
        .expect("Error saving file bytes");
    store
        .store_file_bytes(catnip.bytes(), false)
        .await
        .expect("Error saving catnip file bytes");

    let digest_entries = store
        .entries_for_directory(recursive_testdir.directory_digest())
        .await
        .expect("Getting FileContents");

    assert_same_digest_entries(
        digest_entries,
        vec![
            DigestEntry::File(FileEntry {
                path: PathBuf::from("cats").join("roland.ext"),
                digest: roland.digest(),
                is_executable: false,
            }),
            DigestEntry::File(FileEntry {
                path: PathBuf::from("treats.ext"),
                digest: catnip.digest(),
                is_executable: false,
            }),
        ],
    );

    let empty_digest_entries = store
        .entries_for_directory(EMPTY_DIRECTORY_DIGEST.clone())
        .await
        .expect("Getting EMTPY_DIGEST");

    assert_same_digest_entries(empty_digest_entries, vec![]);
}

fn assert_same_digest_entries(left: Vec<DigestEntry>, right: Vec<DigestEntry>) {
    assert_eq!(
        left.len(),
        right.len(),
        "DigestEntry vectors did not match, different lengths: left: {left:?} right: {right:?}"
    );

    let mut success = true;
    for (index, (l, r)) in left.iter().zip(right.iter()).enumerate() {
        match (l, r) {
            (DigestEntry::File(l), DigestEntry::File(r)) => {
                if l.path != r.path {
                    success = false;
                    eprintln!(
                        "Paths did not match for index {}: {:?}, {:?}",
                        index, l.path, r.path
                    );
                }
                if l.digest != r.digest {
                    success = false;
                    eprintln!(
                        "Digest did not match for index {}: {:?}, {:?}",
                        index, l.digest, r.digest
                    );
                }
                if l.is_executable != r.is_executable {
                    success = false;
                    eprintln!(
                        "Executable bit did not match for index {}: {:?}, {:?}",
                        index, l.is_executable, r.is_executable
                    );
                }
            }
            (DigestEntry::EmptyDirectory(path_left), DigestEntry::EmptyDirectory(path_right)) => {
                if path_left != path_right {
                    success = false;
                    eprintln!(
            "Paths did not match for empty directory at index {index}: {path_left:?}, {path_right:?}"
          );
                }
            }
            (l, r) => {
                success = false;
                eprintln!("Differing types at index {index}: {l:?}, {r:?}")
            }
        }
    }
    assert!(
        success,
        "FileEntry vectors did not match: Left: {left:?}, Right: {right:?}"
    );
}

fn list_dir(path: &Path) -> Vec<String> {
    let mut v: Vec<_> = std::fs::read_dir(path)
        .expect("Listing dir")
        .map(|entry| {
            entry
                .expect("Error reading entry")
                .file_name()
                .to_string_lossy()
                .to_string()
        })
        .collect();
    v.sort();
    v
}

fn file_contents(path: &Path) -> Bytes {
    let mut contents = Vec::new();
    std::fs::File::open(path)
        .and_then(|mut f| f.read_to_end(&mut contents))
        .expect("Error reading file");
    Bytes::from(contents)
}

fn is_executable(path: &Path) -> bool {
    let mode = std::fs::metadata(path)
        .expect("Getting metadata")
        .permissions()
        .mode();

    // NB: macOS's default umask is applied when we create files, and removes the executable bit
    // for "all". There probably isn't a good reason to try to override that.
    let executable_mask = if cfg!(target_os = "macos") {
        0o110
    } else {
        0o111
    };
    mode & executable_mask == executable_mask
}

fn is_readonly(path: &Path) -> bool {
    std::fs::metadata(path)
        .expect("Getting metadata")
        .permissions()
        .readonly()
}

#[tokio::test]
async fn returns_upload_summary_on_empty_cas() {
    let dir = TempDir::new().unwrap();
    let cas = new_empty_cas();

    let testroland = TestData::roland();
    let testcatnip = TestData::catnip();
    let testdir = TestDirectory::containing_roland_and_treats();

    let local_store = new_local_store(dir.path());
    local_store
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error storing directory locally");
    local_store
        .store_file_bytes(testroland.bytes(), false)
        .await
        .expect("Error storing file locally");
    local_store
        .store_file_bytes(testcatnip.bytes(), false)
        .await
        .expect("Error storing file locally");
    let mut summary = new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testdir.digest()])
        .await
        .expect("Error uploading file");

    // We store all 3 files, and so we must sum their digests
    let test_data = vec![
        testdir.digest().size_bytes,
        testroland.digest().size_bytes,
        testcatnip.digest().size_bytes,
    ];
    let test_bytes = test_data.iter().sum();
    summary.upload_wall_time = Duration::default();
    assert_eq!(
        summary,
        UploadSummary {
            ingested_file_count: test_data.len(),
            ingested_file_bytes: test_bytes,
            uploaded_file_count: test_data.len(),
            uploaded_file_bytes: test_bytes,
            upload_wall_time: Duration::default(),
        }
    );
}

#[tokio::test]
async fn summary_does_not_count_things_in_cas() {
    let dir = TempDir::new().unwrap();
    let cas = new_empty_cas();

    let testroland = TestData::roland();
    let testcatnip = TestData::catnip();
    let testdir = TestDirectory::containing_roland_and_treats();

    // Store everything locally
    let local_store = new_local_store(dir.path());
    local_store
        .record_directory(&testdir.directory(), false)
        .await
        .expect("Error storing directory locally");
    local_store
        .store_file_bytes(testroland.bytes(), false)
        .await
        .expect("Error storing file locally");
    local_store
        .store_file_bytes(testcatnip.bytes(), false)
        .await
        .expect("Error storing file locally");

    // Store testroland first, which should return a summary of one file
    let mut data_summary = new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testroland.digest()])
        .await
        .expect("Error uploading file");
    data_summary.upload_wall_time = Duration::default();

    assert_eq!(
        data_summary,
        UploadSummary {
            ingested_file_count: 1,
            ingested_file_bytes: testroland.digest().size_bytes,
            uploaded_file_count: 1,
            uploaded_file_bytes: testroland.digest().size_bytes,
            upload_wall_time: Duration::default(),
        }
    );

    // Store the directory and catnip.
    // It should see the digest of testroland already in cas,
    // and not report it in uploads.
    let mut dir_summary = new_store(dir.path(), &cas.address())
        .await
        .ensure_remote_has_recursive(vec![testdir.digest()])
        .await
        .expect("Error uploading directory");

    dir_summary.upload_wall_time = Duration::default();

    assert_eq!(
        dir_summary,
        UploadSummary {
            ingested_file_count: 3,
            ingested_file_bytes: testdir.digest().size_bytes
                + testroland.digest().size_bytes
                + testcatnip.digest().size_bytes,
            uploaded_file_count: 2,
            uploaded_file_bytes: testdir.digest().size_bytes + testcatnip.digest().size_bytes,
            upload_wall_time: Duration::default(),
        }
    );
}

#[tokio::test]
async fn explicitly_overwrites_already_existing_file() {
    fn test_file_with_arbitrary_content(filename: &str, content: &TestData) -> TestDirectory {
        let digest = content.digest();
        let directory = remexec::Directory {
            files: vec![remexec::FileNode {
                name: filename.to_owned(),
                digest: Some((&digest).into()),
                is_executable: false,
                ..Default::default()
            }],
            ..Default::default()
        };
        TestDirectory { directory }
    }

    let dir_to_write_to = tempfile::tempdir().unwrap();
    let file_path: PathBuf = [dir_to_write_to.path(), Path::new("some_filename.ext")]
        .iter()
        .collect();

    std::fs::write(&file_path, "XXX").unwrap();

    let file_contents = std::fs::read(&file_path).unwrap();
    assert_eq!(file_contents, b"XXX".to_vec());

    let cas_file = TestData::new("abc123");
    let contents_dir = test_file_with_arbitrary_content("some_filename.ext", &cas_file);
    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder()
        .directory(&contents_dir)
        .file(&cas_file)
        .build();
    let store_dir = tempfile::tempdir().unwrap();
    let store = new_store(store_dir.path(), &cas.address()).await;

    store
        .materialize_directory(
            dir_to_write_to.path().to_owned(),
            dir_to_write_to.path(),
            contents_dir.directory_digest(),
            false,
            &BTreeSet::new(),
            Permissions::Writable,
        )
        .await
        .unwrap();

    let file_contents = std::fs::read(&file_path).unwrap();
    assert_eq!(file_contents, b"abc123".to_vec());
}

#[tokio::test]
async fn big_file_immutable_link() {
    let materialize_dir = TempDir::new().unwrap();
    let input_file = materialize_dir.path().join("input_file");
    let output_file = materialize_dir.path().join("output_file");
    let output_dir = materialize_dir.path().join("output_dir");
    let nested_output_file = output_dir.join("file");

    let testdata = TestData::double_all_the_henries();
    let file_bytes = testdata.bytes();
    let file_digest = testdata.digest();

    let nested_directory = remexec::Directory {
        files: vec![remexec::FileNode {
            name: "file".to_owned(),
            digest: Some(file_digest.into()),
            is_executable: true,
            ..remexec::FileNode::default()
        }],
        ..remexec::Directory::default()
    };
    let directory = remexec::Directory {
        files: vec![
            remexec::FileNode {
                name: "input_file".to_owned(),
                digest: Some(file_digest.into()),
                is_executable: true,
                ..remexec::FileNode::default()
            },
            remexec::FileNode {
                name: "output_file".to_owned(),
                digest: Some(file_digest.into()),
                is_executable: true,
                ..remexec::FileNode::default()
            },
        ],
        directories: vec![remexec::DirectoryNode {
            name: "output_dir".to_string(),
            digest: Some(hashing::Digest::of_bytes(&nested_directory.to_bytes()).into()),
        }],
        ..remexec::Directory::default()
    };
    let directory_digest = fs::DirectoryDigest::from_persisted_digest(hashing::Digest::of_bytes(
        &directory.to_bytes(),
    ));

    let store_dir = TempDir::new().unwrap();
    let store = new_local_store(store_dir.path());
    store
        .record_directory(&nested_directory, false)
        .await
        .expect("Error saving Directory");
    store
        .record_directory(&directory, false)
        .await
        .expect("Error saving Directory");
    store
        .store_file_bytes(file_bytes.clone(), false)
        .await
        .expect("Error saving bytes");

    store
        .materialize_directory(
            materialize_dir.path().to_owned(),
            materialize_dir.path(),
            directory_digest,
            false,
            &BTreeSet::from([
                RelativePath::new("output_file").unwrap(),
                RelativePath::new("output_dir").unwrap(),
            ]),
            Permissions::Writable,
        )
        .await
        .expect("Error materializing file");

    let assert_is_linked = |path: &PathBuf, is_linked: bool| {
        assert_eq!(file_contents(path), file_bytes);
        assert!(is_executable(path));
        assert_eq!(path.metadata().unwrap().permissions().readonly(), is_linked);
    };

    assert_is_linked(&input_file, true);
    assert_is_linked(&output_file, false);
    assert_is_linked(&nested_output_file, false);
}
