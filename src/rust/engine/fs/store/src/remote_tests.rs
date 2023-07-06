// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use bytes::Bytes;
use hashing::{Digest, Fingerprint};
use parking_lot::Mutex;
use testutil::data::TestData;
use tokio::io::{AsyncReadExt, AsyncSeekExt, AsyncWriteExt};
use workunit_store::WorkunitStore;

use crate::remote::{ByteSource, ByteStore, ByteStoreProvider, LoadDestination};
use crate::MEGABYTES;

#[tokio::test]
async fn loads_file() {
  let _ = WorkunitStore::setup_for_tests();
  let testdata = TestData::roland();
  let store = new_byte_store(&testdata);

  assert_eq!(
    store.load_bytes(testdata.digest()).await,
    Ok(Some(testdata.bytes()))
  );
}

#[tokio::test]
async fn loads_huge_file_via_temp_file() {
  // 5MB of data
  let testdata = TestData::new(&"12345".repeat(MEGABYTES));

  let _ = WorkunitStore::setup_for_tests();
  let store = new_byte_store(&testdata);

  let file = tokio::task::spawn_blocking(tempfile::tempfile)
    .await
    .unwrap()
    .unwrap();
  let file = tokio::fs::File::from_std(file);

  let mut file = store
    .load_file(testdata.digest(), file)
    .await
    .unwrap()
    .unwrap();
  file.rewind().await.unwrap();

  let mut buf = String::new();
  file.read_to_string(&mut buf).await.unwrap();
  assert_eq!(buf.len(), testdata.len());
  // (assert_eq! means failures unhelpfully print a 5MB string)
  assert!(buf == testdata.string());
}

#[tokio::test]
async fn missing_file() {
  let _ = WorkunitStore::setup_for_tests();
  let (store, _) = empty_byte_store();

  assert_eq!(
    store.load_bytes(TestData::roland().digest()).await,
    Ok(None)
  );
}

#[tokio::test]
async fn load_file_grpc_error() {
  let _ = WorkunitStore::setup_for_tests();
  let store = byte_store_always_error_provider();

  assert_error(store.load_bytes(TestData::roland().digest()).await);
}

#[tokio::test]
async fn write_file_one_chunk() {
  let _ = WorkunitStore::setup_for_tests();
  let testdata = TestData::roland();

  let (store, provider) = empty_byte_store();
  assert_eq!(store.store_bytes(testdata.bytes()).await, Ok(()));

  let blobs = provider.blobs.lock();
  assert_eq!(blobs.get(&testdata.fingerprint()), Some(&testdata.bytes()));
}

#[tokio::test]
async fn write_file_errors() {
  let _ = WorkunitStore::setup_for_tests();
  let store = byte_store_always_error_provider();
  assert_error(store.store_bytes(TestData::roland().bytes()).await)
}

#[tokio::test]
async fn list_missing_digests_none_missing() {
  let _ = WorkunitStore::setup_for_tests();
  let testdata = TestData::roland();
  let store = new_byte_store(&testdata);

  assert_eq!(
    store.list_missing_digests(vec![testdata.digest()]).await,
    Ok(HashSet::new())
  );
}

#[tokio::test]
async fn list_missing_digests_some_missing() {
  let _ = WorkunitStore::setup_for_tests();
  let (store, _) = empty_byte_store();

  let digest = TestData::roland().digest();

  let mut digest_set = HashSet::new();
  digest_set.insert(digest);

  assert_eq!(
    store.list_missing_digests(vec![digest]).await,
    Ok(digest_set)
  );
}

#[tokio::test]
async fn list_missing_digests_error() {
  let _ = WorkunitStore::setup_for_tests();
  let store = byte_store_always_error_provider();

  assert_error(
    store
      .list_missing_digests(vec![TestData::roland().digest()])
      .await,
  )
}

fn new_byte_store(data: &TestData) -> ByteStore {
  let provider = TestProvider::new();
  provider.add(data.bytes());
  ByteStore::new(None, provider)
}

fn empty_byte_store() -> (ByteStore, Arc<TestProvider>) {
  let provider = TestProvider::new();
  (ByteStore::new(None, provider.clone()), provider)
}
fn byte_store_always_error_provider() -> ByteStore {
  ByteStore::new(None, AlwaysErrorProvider::new())
}

fn assert_error<T: std::fmt::Debug>(result: Result<T, String>) {
  let error = result.expect_err("Want error");
  assert!(
    error.contains("AlwaysErrorProvider always fails"),
    "Bad error message, got: {error}"
  );
}

struct TestProvider {
  blobs: Mutex<HashMap<Fingerprint, Bytes>>,
}

impl TestProvider {
  #[allow(dead_code)]
  fn new() -> Arc<TestProvider> {
    Arc::new(TestProvider {
      blobs: Mutex::new(HashMap::new()),
    })
  }

  #[allow(dead_code)]
  fn add(&self, bytes: Bytes) {
    self
      .blobs
      .lock()
      .insert(Digest::of_bytes(&bytes).hash, bytes);
  }
}

#[async_trait::async_trait]
impl ByteStoreProvider for TestProvider {
  async fn store_bytes(&self, digest: Digest, bytes: ByteSource) -> Result<(), String> {
    self
      .blobs
      .lock()
      .insert(digest.hash, bytes(0..digest.size_bytes));
    Ok(())
  }

  async fn load(
    &self,
    digest: Digest,
    destination: &mut dyn LoadDestination,
  ) -> Result<bool, String> {
    let bytes = self.blobs.lock().get(&digest.hash).cloned();
    match bytes {
      None => Ok(false),
      Some(bytes) => {
        destination.write_all(&bytes).await.unwrap();
        Ok(true)
      }
    }
  }

  async fn list_missing_digests(
    &self,
    digests: &mut (dyn Iterator<Item = Digest> + Send),
  ) -> Result<HashSet<Digest>, String> {
    let blobs = self.blobs.lock();
    Ok(digests.filter(|d| !blobs.contains_key(&d.hash)).collect())
  }

  fn chunk_size_bytes(&self) -> usize {
    1234
  }
}

struct AlwaysErrorProvider;
impl AlwaysErrorProvider {
  fn new() -> Arc<AlwaysErrorProvider> {
    Arc::new(AlwaysErrorProvider)
  }
}
#[async_trait::async_trait]
impl ByteStoreProvider for AlwaysErrorProvider {
  async fn store_bytes(&self, _: Digest, _: ByteSource) -> Result<(), String> {
    Err("AlwaysErrorProvider always fails".to_owned())
  }

  async fn load(&self, _: Digest, _: &mut dyn LoadDestination) -> Result<bool, String> {
    Err("AlwaysErrorProvider always fails".to_owned())
  }

  async fn list_missing_digests(
    &self,
    _: &mut (dyn Iterator<Item = Digest> + Send),
  ) -> Result<HashSet<Digest>, String> {
    Err("AlwaysErrorProvider always fails".to_owned())
  }

  fn chunk_size_bytes(&self) -> usize {
    unreachable!("shouldn't call this")
  }
}
