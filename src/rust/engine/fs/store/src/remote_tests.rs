use std::collections::{BTreeMap, HashSet};
use std::time::Duration;

use bytes::Bytes;
use hashing::Digest;
use mock::StubCAS;
use testutil::data::{TestData, TestDirectory};

use crate::remote::ByteStore;
use crate::tests::{big_file_bytes, big_file_fingerprint, new_cas};
use crate::MEGABYTES;

#[tokio::test]
async fn loads_file() {
  let testdata = TestData::roland();
  let cas = new_cas(10);

  assert_eq!(
    load_file_bytes(&new_byte_store(&cas), testdata.digest())
      .await
      .unwrap(),
    Some(testdata.bytes())
  );
}

#[tokio::test]
async fn missing_file() {
  let cas = StubCAS::empty();

  assert_eq!(
    load_file_bytes(&new_byte_store(&cas), TestData::roland().digest()).await,
    Ok(None)
  );
}

#[tokio::test]
async fn load_directory() {
  let cas = new_cas(10);
  let testdir = TestDirectory::containing_roland();

  assert_eq!(
    load_directory_proto_bytes(&new_byte_store(&cas), testdir.digest()).await,
    Ok(Some(testdir.bytes()))
  );
}

#[tokio::test]
async fn missing_directory() {
  let cas = StubCAS::empty();

  assert_eq!(
    load_directory_proto_bytes(
      &new_byte_store(&cas),
      TestDirectory::containing_roland().digest()
    )
    .await,
    Ok(None)
  );
}

#[tokio::test]
async fn load_file_grpc_error() {
  let cas = StubCAS::always_errors();

  let error = load_file_bytes(&new_byte_store(&cas), TestData::roland().digest())
    .await
    .expect_err("Want error");
  assert!(
    error.contains("StubCAS is configured to always fail"),
    "Bad error message, got: {}",
    error
  )
}

#[tokio::test]
async fn load_directory_grpc_error() {
  let cas = StubCAS::always_errors();

  let error = load_directory_proto_bytes(
    &new_byte_store(&cas),
    TestDirectory::containing_roland().digest(),
  )
  .await
  .expect_err("Want error");
  assert!(
    error.contains("StubCAS is configured to always fail"),
    "Bad error message, got: {}",
    error
  )
}

#[tokio::test]
async fn fetch_less_than_one_chunk() {
  let testdata = TestData::roland();
  let cas = new_cas(testdata.bytes().len() + 1);

  assert_eq!(
    load_file_bytes(&new_byte_store(&cas), testdata.digest()).await,
    Ok(Some(testdata.bytes()))
  )
}

#[tokio::test]
async fn fetch_exactly_one_chunk() {
  let testdata = TestData::roland();
  let cas = new_cas(testdata.bytes().len());

  assert_eq!(
    load_file_bytes(&new_byte_store(&cas), testdata.digest()).await,
    Ok(Some(testdata.bytes()))
  )
}

#[tokio::test]
async fn fetch_multiple_chunks_exact() {
  let testdata = TestData::roland();
  let cas = new_cas(1);

  assert_eq!(
    load_file_bytes(&new_byte_store(&cas), testdata.digest()).await,
    Ok(Some(testdata.bytes()))
  )
}

#[tokio::test]
async fn fetch_multiple_chunks_nonfactor() {
  let testdata = TestData::roland();
  let cas = new_cas(9);

  assert_eq!(
    load_file_bytes(&new_byte_store(&cas), testdata.digest()).await,
    Ok(Some(testdata.bytes()))
  )
}

#[tokio::test]
async fn write_file_one_chunk() {
  let testdata = TestData::roland();
  let cas = StubCAS::empty();

  let store = new_byte_store(&cas);
  assert_eq!(store.store_bytes(testdata.bytes()).await, Ok(()));

  let blobs = cas.blobs.lock();
  assert_eq!(blobs.get(&testdata.fingerprint()), Some(&testdata.bytes()));
}

#[tokio::test]
async fn write_file_multiple_chunks() {
  let cas = StubCAS::empty();

  let store = ByteStore::new(
    &cas.address(),
    None,
    None,
    BTreeMap::new(),
    10 * 1024,
    Duration::from_secs(5),
    1,
  )
  .unwrap();

  let all_the_henries = big_file_bytes();

  let fingerprint = big_file_fingerprint();

  assert_eq!(store.store_bytes(all_the_henries.clone()).await, Ok(()));

  let blobs = cas.blobs.lock();
  assert_eq!(blobs.get(&fingerprint), Some(&all_the_henries));

  let write_message_sizes = cas.write_message_sizes.lock();
  assert_eq!(
    write_message_sizes.len(),
    98,
    "Wrong number of chunks uploaded"
  );
  for size in write_message_sizes.iter() {
    assert!(
      size <= &(10 * 1024),
      "Size {} should have been <= {}",
      size,
      10 * 1024
    );
  }
}

#[tokio::test]
async fn write_empty_file() {
  let empty_file = TestData::empty();
  let cas = StubCAS::empty();

  let store = new_byte_store(&cas);
  assert_eq!(store.store_bytes(empty_file.bytes()).await, Ok(()));

  let blobs = cas.blobs.lock();
  assert_eq!(
    blobs.get(&empty_file.fingerprint()),
    Some(&empty_file.bytes())
  );
}

#[tokio::test]
async fn write_file_errors() {
  let cas = StubCAS::always_errors();

  let store = new_byte_store(&cas);
  let error = store
    .store_bytes(TestData::roland().bytes())
    .await
    .expect_err("Want error");
  assert!(
    error.contains("StubCAS is configured to always fail"),
    "Bad error message, got: {}",
    error
  );
}

#[tokio::test]
async fn write_connection_error() {
  let store = ByteStore::new(
    "http://doesnotexist.example",
    None,
    None,
    BTreeMap::new(),
    10 * 1024 * 1024,
    Duration::from_secs(1),
    1,
  )
  .unwrap();
  let error = store
    .store_bytes(TestData::roland().bytes())
    .await
    .expect_err("Want error");
  assert!(
    error.contains("dns error: failed to lookup address information"),
    "Bad error message, got: {}",
    error
  );
}

#[tokio::test]
async fn list_missing_digests_none_missing() {
  let cas = new_cas(1024);

  let store = new_byte_store(&cas);
  assert_eq!(
    store
      .list_missing_digests(
        store.find_missing_blobs_request(vec![TestData::roland().digest()].iter()),
      )
      .await,
    Ok(HashSet::new())
  );
}

#[tokio::test]
async fn list_missing_digests_some_missing() {
  let cas = StubCAS::empty();

  let store = new_byte_store(&cas);

  let digest = TestData::roland().digest();

  let mut digest_set = HashSet::new();
  digest_set.insert(digest);

  assert_eq!(
    store
      .list_missing_digests(store.find_missing_blobs_request(vec![digest].iter()),)
      .await,
    Ok(digest_set)
  );
}

#[tokio::test]
async fn list_missing_digests_error() {
  let cas = StubCAS::always_errors();

  let store = new_byte_store(&cas);

  let error = store
    .list_missing_digests(
      store.find_missing_blobs_request(vec![TestData::roland().digest()].iter()),
    )
    .await
    .expect_err("Want error");
  assert!(
    error.contains("StubCAS is configured to always fail"),
    "Bad error message, got: {}",
    error
  );
}

fn new_byte_store(cas: &StubCAS) -> ByteStore {
  ByteStore::new(
    &cas.address(),
    None,
    None,
    BTreeMap::new(),
    10 * MEGABYTES,
    Duration::from_secs(1),
    1,
  )
  .unwrap()
}

pub async fn load_file_bytes(store: &ByteStore, digest: Digest) -> Result<Option<Bytes>, String> {
  load_bytes(&store, digest).await
}

pub async fn load_directory_proto_bytes(
  store: &ByteStore,
  digest: Digest,
) -> Result<Option<Bytes>, String> {
  load_bytes(&store, digest).await
}

async fn load_bytes(store: &ByteStore, digest: Digest) -> Result<Option<Bytes>, String> {
  store.load_bytes_with(digest, |b| Ok(b)).await
}
