use std::collections::{BTreeMap, HashMap};
use std::fs::File;
use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};

use bytes::{Bytes, BytesMut};
use fs::{DigestEntry, FileEntry, Permissions, EMPTY_DIRECTORY_DIGEST};
use grpc_util::prost::MessageExt;
use grpc_util::tls;
use hashing::{Digest, Fingerprint};
use mock::StubCAS;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use workunit_store::WorkunitStore;

use crate::{EntryType, FileContent, Store, StoreError, UploadSummary, MEGABYTES};

pub(crate) const STORE_BATCH_API_SIZE_LIMIT: usize = 4 * 1024 * 1024;

pub fn big_file_fingerprint() -> Fingerprint {
    Fingerprint::from_hex_string("8dfba0adc29389c63062a68d76b2309b9a2486f1ab610c4720beabbdc273301f")
        .unwrap()
}

pub fn big_file_bytes() -> Bytes {
    let mut f = File::open(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("testdata")
            .join("all_the_henries"),
    )
    .expect("Error opening all_the_henries");
    let mut bytes = Vec::new();
    f.read_to_end(&mut bytes)
        .expect("Error reading all_the_henries");
    Bytes::from(bytes)
}

pub fn extra_big_file_fingerprint() -> Fingerprint {
    Fingerprint::from_hex_string("8ae6924fa104396614b99ce1f6aa3b4d85273ef158191b3784c6dbbdb47055cd")
        .unwrap()
}

pub fn extra_big_file_digest() -> Digest {
    Digest::new(extra_big_file_fingerprint(), extra_big_file_bytes().len())
}

pub fn extra_big_file_bytes() -> Bytes {
    let bfb = big_file_bytes();
    let mut bytes = BytesMut::with_capacity(2 * bfb.len());
    bytes.extend_from_slice(&bfb);
    bytes.extend_from_slice(&bfb);
    bytes.freeze()
}

pub async fn load_file_bytes(store: &Store, digest: Digest) -> Result<Bytes, StoreError> {
    store
        .load_file_bytes_with(digest, |bytes| Bytes::copy_from_slice(bytes))
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

///
/// Create a new store with a remote CAS.
///
fn new_store<P: AsRef<Path>>(dir: P, cas_address: &str) -> Store {
    Store::local_only(task_executor::Executor::new(), dir)
        .unwrap()
        .into_with_remote(
            cas_address,
            None,
            tls::Config::default(),
            BTreeMap::new(),
            10 * MEGABYTES,
            Duration::from_secs(1),
            1,
            256,
            None,
            STORE_BATCH_API_SIZE_LIMIT,
        )
        .unwrap()
}

#[tokio::test]
async fn load_file_prefers_local() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    crate::local_tests::new_store(dir.path())
        .store_bytes(EntryType::File, None, testdata.bytes(), false)
        .await
        .expect("Store failed");

    let cas = new_cas(1024);
    assert_eq!(
        load_file_bytes(&new_store(dir.path(), &cas.address()), testdata.digest()).await,
        Ok(testdata.bytes())
    );
    assert_eq!(0, cas.read_request_count());
}

#[tokio::test]
async fn load_directory_prefers_local() {
    let dir = TempDir::new().unwrap();

    let testdir = TestDirectory::containing_roland();

    crate::local_tests::new_store(dir.path())
        .store_bytes(EntryType::Directory, None, testdir.bytes(), false)
        .await
        .expect("Store failed");

    let cas = new_cas(1024);
    assert_eq!(
        new_store(dir.path(), &cas.address())
            .load_directory(testdir.digest(),)
            .await
            .unwrap(),
        testdir.directory()
    );
    assert_eq!(0, cas.read_request_count());
}

#[tokio::test]
async fn load_file_falls_back_and_backfills() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    let cas = new_cas(1024);
    assert_eq!(
        load_file_bytes(&new_store(dir.path(), &cas.address()), testdata.digest()).await,
        Ok(testdata.bytes()),
        "Read from CAS"
    );
    assert_eq!(1, cas.read_request_count());
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
async fn load_directory_falls_back_and_backfills() {
    let dir = TempDir::new().unwrap();

    let cas = new_cas(1024);

    let testdir = TestDirectory::containing_roland();

    assert_eq!(
        new_store(dir.path(), &cas.address())
            .load_directory(testdir.digest(),)
            .await
            .unwrap(),
        testdir.directory()
    );
    assert_eq!(1, cas.read_request_count());
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
        .ensure_local_has_recursive_directory(recursive_testdir_digest.clone())
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
        &new_store(dir.path(), &cas.address()),
        TestData::roland().digest(),
    )
    .await;
    assert!(matches!(result, Err(StoreError::MissingDigest { .. })),);
    assert_eq!(1, cas.read_request_count());
}

#[tokio::test]
async fn load_directory_missing_errors() {
    let dir = TempDir::new().unwrap();

    let cas = new_empty_cas();
    let result = new_store(dir.path(), &cas.address())
        .load_directory(TestDirectory::containing_roland().digest())
        .await;
    assert!(matches!(result, Err(StoreError::MissingDigest { .. })),);
    assert_eq!(1, cas.read_request_count());
}

#[tokio::test]
async fn load_file_remote_error_is_error() {
    let dir = TempDir::new().unwrap();

    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::cas_always_errors();
    let error = load_file_bytes(
        &new_store(dir.path(), &cas.address()),
        TestData::roland().digest(),
    )
    .await
    .expect_err("Want error");
    assert!(
        cas.read_request_count() > 0,
        "Want read_request_count > 0 but got {}",
        cas.read_request_count()
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
        .load_directory(TestData::roland().digest())
        .await
        .expect_err("Want error");
    assert!(
        cas.read_request_count() > 0,
        "Want read_request_count > 0 but got {}",
        cas.read_request_count()
    );
    assert!(
        error
            .to_string()
            .contains("StubCAS is configured to always fail"),
        "Bad error message"
    );
}

#[tokio::test]
async fn malformed_remote_directory_is_error() {
    let dir = TempDir::new().unwrap();

    let testdata = TestData::roland();

    let cas = new_cas(1024);
    new_store(dir.path(), &cas.address())
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
        let file = remexec::FileNode {
            name: "roland".to_string(),
            digest: Some((&TestData::roland().digest()).into()),
            ..Default::default()
        };
        file
    });
    let non_canonical_directory_bytes = non_canonical_directory.to_bytes();
    let directory_digest = Digest::of_bytes(&non_canonical_directory_bytes);
    let non_canonical_directory_fingerprint = directory_digest.hash;

    let dir = TempDir::new().unwrap();

    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder()
        .unverified_content(
            non_canonical_directory_fingerprint.clone(),
            non_canonical_directory_bytes,
        )
        .build();
    new_store(dir.path(), &cas.address())
        .load_directory(directory_digest.clone())
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
    load_file_bytes(&new_store(dir.path(), &cas.address()), testdata.digest())
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
    load_file_bytes(&new_store(dir.path(), &cas.address()), testdir.digest())
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
        "Bad error: {}",
        error
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
        "Bad error message: {}",
        error
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

    new_local_store(dir.path())
        .store_file_bytes(extra_big_file_bytes(), false)
        .await
        .expect("Error storing file locally");

    new_store(dir.path(), &cas.address())
        .ensure_remote_has_recursive(vec![extra_big_file_digest()])
        .await
        .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().len(), 1);
    assert_eq!(
        cas.blobs.lock().get(&extra_big_file_fingerprint()),
        Some(&extra_big_file_bytes())
    );

    new_store(dir.path(), &cas.address())
        .ensure_remote_has_recursive(vec![extra_big_file_digest()])
        .await
        .expect("Error uploading directory");

    assert_eq!(cas.write_message_sizes.lock().len(), 1);
    assert_eq!(
        cas.blobs.lock().get(&extra_big_file_fingerprint()),
        Some(&extra_big_file_bytes())
    );
}

#[tokio::test]
async fn upload_missing_files() {
    let dir = TempDir::new().unwrap();
    let cas = new_empty_cas();

    let testdata = TestData::roland();

    assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);

    let error = new_store(dir.path(), &cas.address())
        .ensure_remote_has_recursive(vec![testdata.digest()])
        .await
        .expect_err("Want error");
    assert!(
        matches!(error, StoreError::MissingDigest { .. }),
        "Bad error: {}",
        error
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
        .ensure_remote_has_recursive(vec![testdir.digest()])
        .await
        .expect_err("Want error");
    assert!(
        matches!(error, StoreError::MissingDigest { .. }),
        "Bad error: {}",
        error
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
        .into_with_remote(
            &cas.address(),
            Some("dark-tower".to_owned()),
            tls::Config::default(),
            BTreeMap::new(),
            10 * MEGABYTES,
            Duration::from_secs(1),
            1,
            256,
            None,
            STORE_BATCH_API_SIZE_LIMIT,
        )
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
        .into_with_remote(
            &cas.address(),
            Some("dark-tower".to_owned()),
            tls::Config::default(),
            BTreeMap::new(),
            10 * MEGABYTES,
            Duration::from_secs(1),
            1,
            256,
            None,
            STORE_BATCH_API_SIZE_LIMIT,
        )
        .unwrap();

    assert_eq!(
        store_with_remote
            .load_file_bytes_with(TestData::roland().digest(), |b| Bytes::copy_from_slice(b))
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
        .into_with_remote(
            &cas.address(),
            None,
            tls::Config::default(),
            headers,
            10 * MEGABYTES,
            Duration::from_secs(1),
            1,
            256,
            None,
            STORE_BATCH_API_SIZE_LIMIT,
        )
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
        .into_with_remote(
            &cas.address(),
            None,
            tls::Config::default(),
            headers,
            10 * MEGABYTES,
            Duration::from_secs(1),
            1,
            256,
            None,
            STORE_BATCH_API_SIZE_LIMIT,
        )
        .unwrap();

    assert_eq!(
        store_with_remote
            .load_file_bytes_with(TestData::roland().digest(), |b| Bytes::copy_from_slice(b))
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
        .materialize_file(file.clone(), TestData::roland().digest(), 0o644)
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
        .materialize_file(file.clone(), testdata.digest(), 0o644)
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
            TestDirectory::recursive().directory_digest(),
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
            recursive_testdir.directory_digest(),
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
    assert_eq!(readonly, is_readonly(&materialize_dir.path()));
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
        "FileContents did not match, different lengths: left: {:?} right: {:?}",
        left,
        right
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
        "FileContents did not match: Left: {:?}, Right: {:?}",
        left, right
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
        "DigestEntry vectors did not match, different lengths: left: {:?} right: {:?}",
        left,
        right
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
                        "Paths did not match for empty directory at index {}: {:?}, {:?}",
                        index, path_left, path_right
                    );
                }
            }
            (l, r) => {
                success = false;
                eprintln!("Differing types at index {}: {:?}, {:?}", index, l, r)
            }
        }
    }
    assert!(
        success,
        "FileEntry vectors did not match: Left: {:?}, Right: {:?}",
        left, right
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
    let store = new_store(tempfile::tempdir().unwrap(), &cas.address());

    let _ = store
        .materialize_directory(
            dir_to_write_to.path().to_owned(),
            contents_dir.directory_digest(),
            Permissions::Writable,
        )
        .await
        .unwrap();

    let file_contents = std::fs::read(&file_path).unwrap();
    assert_eq!(file_contents, b"abc123".to_vec());
}
