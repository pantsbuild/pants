use crate::{
  DirectoryMaterializeMetadata, EntryType, FileContent, LoadMetadata, Store, UploadSummary,
  MEGABYTES,
};

use bazel_protos;
use bytes::Bytes;
use digest::{Digest as DigestTrait, FixedOutput};
use futures::compat::Future01CompatExt;
use hashing::{Digest, Fingerprint};
use maplit::btreemap;
use mock::StubCAS;
use protobuf::Message;
use serverset::BackoffConfig;
use sha2::Sha256;
use std;
use std::collections::HashMap;
use std::fs::File;
use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tempfile::TempDir;
use testutil::data::{TestData, TestDirectory};
use tokio::runtime::Handle;

impl LoadMetadata {
  fn is_remote(&self) -> bool {
    match self {
      LoadMetadata::Local => false,
      LoadMetadata::Remote(_) => true,
    }
  }
}

pub fn big_file_fingerprint() -> Fingerprint {
  Fingerprint::from_hex_string("8dfba0adc29389c63062a68d76b2309b9a2486f1ab610c4720beabbdc273301f")
    .unwrap()
}

pub fn big_file_digest() -> Digest {
  Digest(big_file_fingerprint(), big_file_bytes().len())
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
  Digest(extra_big_file_fingerprint(), extra_big_file_bytes().len())
}

pub fn extra_big_file_bytes() -> Bytes {
  let mut bytes = big_file_bytes();
  bytes.extend(&big_file_bytes());
  bytes
}

pub async fn load_file_bytes(store: &Store, digest: Digest) -> Result<Option<Bytes>, String> {
  let option = store
    .load_file_bytes_with(digest, |bytes| Bytes::from(bytes))
    .await?;
  Ok(option.map(|(bytes, _metadata)| bytes))
}

///
/// Create a StubCas with a file and a directory inside.
///
pub fn new_cas(chunk_size_bytes: usize) -> StubCAS {
  StubCAS::builder()
    .chunk_size_bytes(chunk_size_bytes)
    .file(&TestData::roland())
    .directory(&TestDirectory::containing_roland())
    .build()
}

///
/// Create a new local store with whatever was already serialized in dir.
///
fn new_local_store<P: AsRef<Path>>(dir: P) -> Store {
  Store::local_only(task_executor::Executor::new(Handle::current()), dir)
    .expect("Error creating local store")
}

///
/// Create a new store with a remote CAS.
///
fn new_store<P: AsRef<Path>>(dir: P, cas_address: String) -> Store {
  Store::with_remote(
    task_executor::Executor::new(Handle::current()),
    dir,
    vec![cas_address],
    None,
    None,
    None,
    1,
    10 * MEGABYTES,
    Duration::from_secs(1),
    BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
    1,
    1,
  )
  .unwrap()
}

#[tokio::test]
async fn load_file_prefers_local() {
  let dir = TempDir::new().unwrap();

  let testdata = TestData::roland();

  crate::local_tests::new_store(dir.path())
    .store_bytes(EntryType::File, testdata.bytes(), false)
    .await
    .expect("Store failed");

  let cas = new_cas(1024);
  assert_eq!(
    load_file_bytes(&new_store(dir.path(), cas.address()), testdata.digest()).await,
    Ok(Some(testdata.bytes()))
  );
  assert_eq!(0, cas.read_request_count());
}

#[tokio::test]
async fn load_directory_prefers_local() {
  let dir = TempDir::new().unwrap();

  let testdir = TestDirectory::containing_roland();

  crate::local_tests::new_store(dir.path())
    .store_bytes(EntryType::Directory, testdir.bytes(), false)
    .await
    .expect("Store failed");

  let cas = new_cas(1024);
  assert_eq!(
    new_store(dir.path(), cas.address())
      .load_directory(testdir.digest(),)
      .await
      .unwrap()
      .unwrap()
      .0,
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
    load_file_bytes(&new_store(dir.path(), cas.address()), testdata.digest()).await,
    Ok(Some(testdata.bytes())),
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
    new_store(dir.path(), cas.address())
      .load_directory(testdir.digest(),)
      .await
      .unwrap()
      .unwrap()
      .0,
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
  let recursive_testdir_digest = recursive_testdir.digest();

  let cas = StubCAS::builder()
    .file(&roland)
    .file(&catnip)
    .directory(&testdir)
    .directory(&recursive_testdir)
    .build();

  new_store(dir.path(), cas.address())
    .ensure_local_has_recursive_directory(recursive_testdir_digest)
    .compat()
    .await
    .expect("Downloading recursive directory should have succeeded.");

  assert_eq!(
    load_file_bytes(&new_local_store(dir.path()), roland.digest()).await,
    Ok(Some(roland.bytes()))
  );
  assert_eq!(
    load_file_bytes(&new_local_store(dir.path()), catnip.digest()).await,
    Ok(Some(catnip.bytes()))
  );
  assert_eq!(
    new_local_store(dir.path())
      .load_directory(testdir_digest,)
      .await
      .unwrap()
      .unwrap()
      .0,
    testdir_directory
  );
  assert_eq!(
    new_local_store(dir.path())
      .load_directory(recursive_testdir_digest,)
      .await
      .unwrap()
      .unwrap()
      .0,
    recursive_testdir_directory
  );
}

#[tokio::test]
async fn load_file_missing_is_none() {
  let dir = TempDir::new().unwrap();

  let cas = StubCAS::empty();
  assert_eq!(
    load_file_bytes(
      &new_store(dir.path(), cas.address()),
      TestData::roland().digest()
    )
    .await,
    Ok(None)
  );
  assert_eq!(1, cas.read_request_count());
}

#[tokio::test]
async fn load_directory_missing_is_none() {
  let dir = TempDir::new().unwrap();

  let cas = StubCAS::empty();
  assert_eq!(
    new_store(dir.path(), cas.address())
      .load_directory(TestDirectory::containing_roland().digest(),)
      .await,
    Ok(None)
  );
  assert_eq!(1, cas.read_request_count());
}

#[tokio::test]
async fn load_file_remote_error_is_error() {
  let dir = TempDir::new().unwrap();

  let cas = StubCAS::always_errors();
  let error = load_file_bytes(
    &new_store(dir.path(), cas.address()),
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
    error.contains("StubCAS is configured to always fail"),
    "Bad error message"
  );
}

#[tokio::test]
async fn load_directory_remote_error_is_error() {
  let dir = TempDir::new().unwrap();

  let cas = StubCAS::always_errors();
  let error = new_store(dir.path(), cas.address())
    .load_directory(TestData::roland().digest())
    .await
    .expect_err("Want error");
  assert!(
    cas.read_request_count() > 0,
    "Want read_request_count > 0 but got {}",
    cas.read_request_count()
  );
  assert!(
    error.contains("StubCAS is configured to always fail"),
    "Bad error message"
  );
}

#[tokio::test]
async fn malformed_remote_directory_is_error() {
  let dir = TempDir::new().unwrap();

  let testdata = TestData::roland();

  let cas = new_cas(1024);
  new_store(dir.path(), cas.address())
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
  non_canonical_directory.mut_files().push({
    let mut file = bazel_protos::remote_execution::FileNode::new();
    file.set_name("roland".to_string());
    file.set_digest((&TestData::roland().digest()).into());
    file
  });
  let non_canonical_directory_bytes = Bytes::from(
    non_canonical_directory
      .write_to_bytes()
      .expect("Error serializing proto"),
  );
  let non_canonical_directory_fingerprint = {
    let mut hasher = Sha256::default();
    hasher.input(&non_canonical_directory_bytes);
    Fingerprint::from_bytes_unsafe(hasher.fixed_result().as_slice())
  };
  let directory_digest = Digest(
    non_canonical_directory_fingerprint,
    non_canonical_directory_bytes.len(),
  );

  let dir = TempDir::new().unwrap();

  let cas = StubCAS::builder()
    .unverified_content(
      non_canonical_directory_fingerprint.clone(),
      non_canonical_directory_bytes,
    )
    .build();
  new_store(dir.path(), cas.address())
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

  let cas = StubCAS::builder()
    .unverified_content(
      testdata.fingerprint(),
      TestDirectory::containing_roland().bytes(),
    )
    .build();
  load_file_bytes(&new_store(dir.path(), cas.address()), testdata.digest())
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

  let cas = StubCAS::builder()
    .unverified_content(
      testdir.fingerprint(),
      TestDirectory::containing_roland().bytes(),
    )
    .build();
  load_file_bytes(&new_store(dir.path(), cas.address()), testdir.digest())
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
    .compat()
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
    .compat()
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
    .compat()
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
    .compat()
    .await
    .expect_err("Want error");
  assert!(
    error.contains(&format!("{:?}", digest)),
    "Bad error message: {}",
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
    .compat()
    .await
    .expect_err("Want error");
  assert!(
    error.contains(&format!(
      "{}",
      TestDirectory::containing_roland().fingerprint()
    )),
    "Bad error message: {}",
    error
  );
}

#[tokio::test]
async fn uploads_files() {
  let dir = TempDir::new().unwrap();
  let cas = StubCAS::empty();

  let testdata = TestData::roland();

  new_local_store(dir.path())
    .store_file_bytes(testdata.bytes(), false)
    .await
    .expect("Error storing file locally");

  assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);

  new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![testdata.digest()])
    .compat()
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
  let cas = StubCAS::empty();

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

  new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![testdir.digest()])
    .compat()
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
  let cas = StubCAS::empty();

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

  new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![testdata.digest()])
    .compat()
    .await
    .expect("Error uploading file");

  assert_eq!(cas.write_message_sizes.lock().len(), 1);
  assert_eq!(
    cas.blobs.lock().get(&testdata.fingerprint()),
    Some(&testdata.bytes())
  );
  assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);

  new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![testdir.digest()])
    .compat()
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
  let cas = StubCAS::empty();

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

  new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![roland.digest()])
    .compat()
    .await
    .expect("Error uploading big file");

  assert_eq!(cas.write_message_sizes.lock().len(), 1);
  assert_eq!(
    cas.blobs.lock().get(&roland.fingerprint()),
    Some(&roland.bytes())
  );
  assert_eq!(cas.blobs.lock().get(&catnip.fingerprint()), None);
  assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);

  new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![testdir.digest(), catnip.digest()])
    .compat()
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
  let cas = StubCAS::empty();

  new_local_store(dir.path())
    .store_file_bytes(extra_big_file_bytes(), false)
    .await
    .expect("Error storing file locally");

  new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![extra_big_file_digest()])
    .compat()
    .await
    .expect("Error uploading directory");

  assert_eq!(cas.write_message_sizes.lock().len(), 1);
  assert_eq!(
    cas.blobs.lock().get(&extra_big_file_fingerprint()),
    Some(&extra_big_file_bytes())
  );

  new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![extra_big_file_digest()])
    .compat()
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
  let cas = StubCAS::empty();

  let testdata = TestData::roland();

  assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);

  let error = new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![testdata.digest()])
    .compat()
    .await
    .expect_err("Want error");
  assert_eq!(
    error,
    format!("Failed to expand digest {:?}: Not found", testdata.digest())
  );
}

#[tokio::test]
async fn upload_missing_file_in_directory() {
  let dir = TempDir::new().unwrap();
  let cas = StubCAS::empty();

  let testdir = TestDirectory::containing_roland();

  new_local_store(dir.path())
    .record_directory(&testdir.directory(), false)
    .await
    .expect("Error storing directory locally");

  assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);
  assert_eq!(cas.blobs.lock().get(&testdir.fingerprint()), None);

  let error = new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![testdir.digest()])
    .compat()
    .await
    .expect_err("Want error");
  assert_eq!(
    error,
    format!(
      "Failed to upload digest {:?}: Not found",
      TestData::roland().digest()
    ),
    "Bad error message"
  );
}

#[tokio::test]
async fn uploading_digest_with_wrong_size_is_error() {
  let dir = TempDir::new().unwrap();
  let cas = StubCAS::empty();

  let testdata = TestData::roland();

  new_local_store(dir.path())
    .store_file_bytes(testdata.bytes(), false)
    .await
    .expect("Error storing file locally");

  assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);

  let wrong_digest = Digest(testdata.fingerprint(), testdata.len() + 1);

  new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![wrong_digest])
    .compat()
    .await
    .expect_err("Expect error uploading file");

  assert_eq!(cas.blobs.lock().get(&testdata.fingerprint()), None);
}

#[tokio::test]
async fn instance_name_upload() {
  let dir = TempDir::new().unwrap();
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

  let store_with_remote = Store::with_remote(
    task_executor::Executor::new(Handle::current()),
    dir.path(),
    vec![cas.address()],
    Some("dark-tower".to_owned()),
    None,
    None,
    1,
    10 * MEGABYTES,
    Duration::from_secs(1),
    BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
    1,
    1,
  )
  .unwrap();

  store_with_remote
    .ensure_remote_has_recursive(vec![testdir.digest()])
    .compat()
    .await
    .expect("Error uploading");
}

#[tokio::test]
async fn instance_name_download() {
  let dir = TempDir::new().unwrap();
  let cas = StubCAS::builder()
    .instance_name("dark-tower".to_owned())
    .file(&TestData::roland())
    .build();

  let store_with_remote = Store::with_remote(
    task_executor::Executor::new(Handle::current()),
    dir.path(),
    vec![cas.address()],
    Some("dark-tower".to_owned()),
    None,
    None,
    1,
    10 * MEGABYTES,
    Duration::from_secs(1),
    BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
    1,
    1,
  )
  .unwrap();

  assert_eq!(
    store_with_remote
      .load_file_bytes_with(TestData::roland().digest(), |b| Bytes::from(b))
      .await
      .unwrap()
      .unwrap()
      .0,
    TestData::roland().bytes()
  )
}

#[tokio::test]
async fn auth_upload() {
  let dir = TempDir::new().unwrap();
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

  let store_with_remote = Store::with_remote(
    task_executor::Executor::new(Handle::current()),
    dir.path(),
    vec![cas.address()],
    None,
    None,
    Some("Armory.Key".to_owned()),
    1,
    10 * MEGABYTES,
    Duration::from_secs(1),
    BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
    1,
    1,
  )
  .unwrap();

  store_with_remote
    .ensure_remote_has_recursive(vec![testdir.digest()])
    .compat()
    .await
    .expect("Error uploading");
}

#[tokio::test]
async fn auth_download() {
  let dir = TempDir::new().unwrap();
  let cas = StubCAS::builder()
    .required_auth_token("Armory.Key".to_owned())
    .file(&TestData::roland())
    .build();

  let store_with_remote = Store::with_remote(
    task_executor::Executor::new(Handle::current()),
    dir.path(),
    vec![cas.address()],
    None,
    None,
    Some("Armory.Key".to_owned()),
    1,
    10 * MEGABYTES,
    Duration::from_secs(1),
    BackoffConfig::new(Duration::from_millis(10), 1.0, Duration::from_millis(10)).unwrap(),
    1,
    1,
  )
  .unwrap();

  assert_eq!(
    store_with_remote
      .load_file_bytes_with(TestData::roland().digest(), |b| Bytes::from(b))
      .await
      .unwrap()
      .unwrap()
      .0,
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
    .materialize_file(file.clone(), TestData::roland().digest(), false, true)
    .compat()
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
    .materialize_file(file.clone(), testdata.digest(), false, true)
    .compat()
    .await
    .expect("Error materializing file");
  assert_eq!(file_contents(&file), testdata.bytes());
  assert!(!is_executable(&file));
}

#[tokio::test]
async fn materialize_file_executable() {
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
    .materialize_file(file.clone(), testdata.digest(), true, true)
    .compat()
    .await
    .expect("Error materializing file");
  assert_eq!(file_contents(&file), testdata.bytes());
  assert!(is_executable(&file));
}

#[tokio::test]
async fn materialize_missing_directory() {
  let materialize_dir = TempDir::new().unwrap();

  let store_dir = TempDir::new().unwrap();
  let store = new_local_store(store_dir.path());
  store
    .materialize_directory(
      materialize_dir.path().to_owned(),
      TestDirectory::recursive().digest(),
    )
    .compat()
    .await
    .expect_err("Want unknown digest error");
}

#[tokio::test]
async fn materialize_directory() {
  let materialize_dir = TempDir::new().unwrap();

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

  store
    .materialize_directory(
      materialize_dir.path().to_owned(),
      recursive_testdir.digest(),
    )
    .compat()
    .await
    .expect("Error materializing");

  assert_eq!(list_dir(materialize_dir.path()), vec!["cats", "treats"]);
  assert_eq!(
    file_contents(&materialize_dir.path().join("treats")),
    catnip.bytes()
  );
  assert_eq!(
    list_dir(&materialize_dir.path().join("cats")),
    vec!["roland"]
  );
  assert_eq!(
    file_contents(&materialize_dir.path().join("cats").join("roland")),
    roland.bytes()
  );
}

#[tokio::test]
async fn materialize_directory_executable() {
  let materialize_dir = TempDir::new().unwrap();

  let catnip = TestData::catnip();
  let testdir = TestDirectory::with_mixed_executable_files();

  let store_dir = TempDir::new().unwrap();
  let store = new_local_store(store_dir.path());
  store
    .record_directory(&testdir.directory(), false)
    .await
    .expect("Error saving Directory");
  store
    .store_file_bytes(catnip.bytes(), false)
    .await
    .expect("Error saving catnip file bytes");

  store
    .materialize_directory(materialize_dir.path().to_owned(), testdir.digest())
    .compat()
    .await
    .expect("Error materializing");

  assert_eq!(list_dir(materialize_dir.path()), vec!["feed", "food"]);
  assert_eq!(
    file_contents(&materialize_dir.path().join("feed")),
    catnip.bytes()
  );
  assert_eq!(
    file_contents(&materialize_dir.path().join("food")),
    catnip.bytes()
  );
  assert!(is_executable(&materialize_dir.path().join("feed")));
  assert!(!is_executable(&materialize_dir.path().join("food")));
}

#[tokio::test]
async fn contents_for_directory_empty() {
  let store_dir = TempDir::new().unwrap();
  let store = new_local_store(store_dir.path());

  let file_contents = store
    .contents_for_directory(TestDirectory::empty().digest())
    .compat()
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
    .contents_for_directory(recursive_testdir.digest())
    .compat()
    .await
    .expect("Getting FileContents");

  assert_same_filecontents(
    file_contents,
    vec![
      FileContent {
        path: PathBuf::from("cats").join("roland"),
        content: roland.bytes(),
        is_executable: false,
      },
      FileContent {
        path: PathBuf::from("treats"),
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
  std::fs::metadata(path)
    .expect("Getting metadata")
    .permissions()
    .mode()
    & 0o100
    == 0o100
}

#[tokio::test]
async fn returns_upload_summary_on_empty_cas() {
  let dir = TempDir::new().unwrap();
  let cas = StubCAS::empty();

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
  let mut summary = new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![testdir.digest()])
    .compat()
    .await
    .expect("Error uploading file");

  // We store all 3 files, and so we must sum their digests
  let test_data = vec![
    testdir.digest().1,
    testroland.digest().1,
    testcatnip.digest().1,
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
  let cas = StubCAS::empty();

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
  let mut data_summary = new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![testroland.digest()])
    .compat()
    .await
    .expect("Error uploading file");
  data_summary.upload_wall_time = Duration::default();

  assert_eq!(
    data_summary,
    UploadSummary {
      ingested_file_count: 1,
      ingested_file_bytes: testroland.digest().1,
      uploaded_file_count: 1,
      uploaded_file_bytes: testroland.digest().1,
      upload_wall_time: Duration::default(),
    }
  );

  // Store the directory and catnip.
  // It should see the digest of testroland already in cas,
  // and not report it in uploads.
  let mut dir_summary = new_store(dir.path(), cas.address())
    .ensure_remote_has_recursive(vec![testdir.digest()])
    .compat()
    .await
    .expect("Error uploading directory");

  dir_summary.upload_wall_time = Duration::default();

  assert_eq!(
    dir_summary,
    UploadSummary {
      ingested_file_count: 3,
      ingested_file_bytes: testdir.digest().1 + testroland.digest().1 + testcatnip.digest().1,
      uploaded_file_count: 2,
      uploaded_file_bytes: testdir.digest().1 + testcatnip.digest().1,
      upload_wall_time: Duration::default(),
    }
  );
}

#[tokio::test]
async fn materialize_directory_metadata_all_local() {
  let outer_dir = TestDirectory::double_nested();
  let nested_dir = TestDirectory::nested();
  let inner_dir = TestDirectory::containing_roland();
  let file = TestData::roland();

  let dir = tempfile::tempdir().unwrap();
  let store = new_local_store(dir.path());
  store
    .record_directory(&outer_dir.directory(), false)
    .await
    .expect("Error storing directory locally");
  store
    .record_directory(&nested_dir.directory(), false)
    .await
    .expect("Error storing directory locally");
  store
    .record_directory(&inner_dir.directory(), false)
    .await
    .expect("Error storing directory locally");
  store
    .store_file_bytes(file.bytes(), false)
    .await
    .expect("Error storing file locally");

  let mat_dir = tempfile::tempdir().unwrap();
  let metadata = store
    .materialize_directory(mat_dir.path().to_owned(), outer_dir.digest())
    .compat()
    .await
    .unwrap();

  let local = LoadMetadata::Local;

  let want = DirectoryMaterializeMetadata {
    metadata: local.clone(),
    child_directories: btreemap! {
      "pets".to_owned() => DirectoryMaterializeMetadata {
        metadata: local.clone(),
        child_directories: btreemap!{
          "cats".to_owned() => DirectoryMaterializeMetadata {
            metadata: local.clone(),
            child_directories: btreemap!{},
            child_files: btreemap!{
              "roland".to_owned() => local.clone(),
            },
          }
        },
        child_files: btreemap!{},
      }
    },
    child_files: btreemap! {},
  };

  assert_eq!(want, metadata);
}

#[tokio::test]
async fn materialize_directory_metadata_mixed() {
  let outer_dir = TestDirectory::double_nested(); // /pets/cats/roland
  let nested_dir = TestDirectory::nested(); // /cats/roland
  let inner_dir = TestDirectory::containing_roland();
  let file = TestData::roland();

  let cas = StubCAS::builder().directory(&nested_dir).build();

  let dir = tempfile::tempdir().unwrap();
  let store = new_store(dir.path(), cas.address());
  store
    .record_directory(&outer_dir.directory(), false)
    .await
    .expect("Error storing directory locally");
  store
    .record_directory(&inner_dir.directory(), false)
    .await
    .expect("Error storing directory locally");
  store
    .store_file_bytes(file.bytes(), false)
    .await
    .expect("Error storing file locally");

  let mat_dir = tempfile::tempdir().unwrap();
  let metadata = store
    .materialize_directory(mat_dir.path().to_owned(), outer_dir.digest())
    .compat()
    .await
    .unwrap();

  assert!(metadata
    .child_directories
    .get("pets")
    .unwrap()
    .metadata
    .is_remote());
  assert_eq!(
    LoadMetadata::Local,
    *metadata
      .child_directories
      .get("pets")
      .unwrap()
      .child_directories
      .get("cats")
      .unwrap()
      .child_files
      .get("roland")
      .unwrap()
  );
}

#[tokio::test]
async fn explicitly_overwrites_already_existing_file() {
  fn test_file_with_arbitrary_content(filename: &str, content: &TestData) -> TestDirectory {
    use bazel_protos;
    let digest = content.digest();
    let mut directory = bazel_protos::remote_execution::Directory::new();
    directory.mut_files().push({
      let mut file = bazel_protos::remote_execution::FileNode::new();
      file.set_name(filename.to_owned());
      file.set_digest((&digest).into());
      file.set_is_executable(false);
      file
    });
    TestDirectory { directory }
  }

  let dir_to_write_to = tempfile::tempdir().unwrap();
  let file_path: PathBuf = [dir_to_write_to.path(), Path::new("some_filename")]
    .iter()
    .collect();

  std::fs::write(&file_path, "XXX").unwrap();

  let file_contents = std::fs::read(&file_path).unwrap();
  assert_eq!(file_contents, b"XXX".to_vec());

  let cas_file = TestData::new("abc123");
  let contents_dir = test_file_with_arbitrary_content("some_filename", &cas_file);
  let cas = StubCAS::builder()
    .directory(&contents_dir)
    .file(&cas_file)
    .build();
  let store = new_store(tempfile::tempdir().unwrap(), cas.address());

  let _ = store
    .materialize_directory(dir_to_write_to.path().to_owned(), contents_dir.digest())
    .compat()
    .await
    .unwrap();

  let file_contents = std::fs::read(&file_path).unwrap();
  assert_eq!(file_contents, b"abc123".to_vec());
}
