// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, HashSet};
use std::time::Duration;

use bytes::Bytes;
use grpc_util::tls;
use hashing::Digest;
use mock::StubCAS;
use testutil::data::TestData;
use tokio::io::{AsyncReadExt, AsyncSeekExt};
use workunit_store::WorkunitStore;

use crate::remote::{ByteStore, RemoteOptions};
use crate::tests::new_cas;
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
async fn loads_huge_file_via_temp_file() {
  // 5MB of data
  let testdata = TestData::new(&"12345".repeat(MEGABYTES));

  let _ = WorkunitStore::setup_for_tests();
  let cas = StubCAS::builder()
    .chunk_size_bytes(MEGABYTES)
    .file(&testdata)
    .build();

  let file = tokio::task::spawn_blocking(tempfile::tempfile)
    .await
    .unwrap()
    .unwrap();
  let file = tokio::fs::File::from_std(file);

  let mut file = new_byte_store(&cas)
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
  let cas = StubCAS::empty();

  assert_eq!(
    load_file_bytes(&new_byte_store(&cas), TestData::roland().digest()).await,
    Ok(None)
  );
}

#[tokio::test]
async fn load_file_grpc_error() {
  let _ = WorkunitStore::setup_for_tests();
  let cas = StubCAS::cas_always_errors();

  let error = load_file_bytes(&new_byte_store(&cas), TestData::roland().digest())
    .await
    .expect_err("Want error");
  assert!(
    error.contains("StubCAS is configured to always fail"),
    "Bad error message, got: {error}"
  )
}

#[tokio::test]
async fn write_file_one_chunk() {
  let _ = WorkunitStore::setup_for_tests();
  let testdata = TestData::roland();
  let cas = StubCAS::empty();

  let store = new_byte_store(&cas);
  assert_eq!(store.store_bytes(testdata.bytes()).await, Ok(()));

  let blobs = cas.blobs.lock();
  assert_eq!(blobs.get(&testdata.fingerprint()), Some(&testdata.bytes()));
}

fn remote_options(
  cas_address: String,
  chunk_size_bytes: usize,
  batch_api_size_limit: usize,
) -> RemoteOptions {
  RemoteOptions {
    cas_address,
    instance_name: None,
    tls_config: tls::Config::default(),
    headers: BTreeMap::new(),
    chunk_size_bytes,
    rpc_timeout: Duration::from_secs(5),
    rpc_retries: 1,
    rpc_concurrency_limit: 256,
    capabilities_cell_opt: None,
    batch_api_size_limit,
  }
}

#[tokio::test]
async fn write_file_errors() {
  let _ = WorkunitStore::setup_for_tests();
  let cas = StubCAS::cas_always_errors();

  let store = new_byte_store(&cas);
  let error = store
    .store_bytes(TestData::roland().bytes())
    .await
    .expect_err("Want error");
  assert!(
    error.contains("StubCAS is configured to always fail"),
    "Bad error message, got: {error}"
  );
}

#[tokio::test]
async fn list_missing_digests_none_missing() {
  let cas = new_cas(1024);

  let store = new_byte_store(&cas);
  assert_eq!(
    store
      .list_missing_digests(vec![TestData::roland().digest()])
      .await,
    Ok(HashSet::new())
  );
}

#[tokio::test]
async fn list_missing_digests_some_missing() {
  let _ = WorkunitStore::setup_for_tests();
  let cas = StubCAS::empty();

  let store = new_byte_store(&cas);

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
  let cas = StubCAS::cas_always_errors();

  let store = new_byte_store(&cas);

  let error = store
    .list_missing_digests(vec![TestData::roland().digest()])
    .await
    .expect_err("Want error");
  assert!(
    error.contains("StubCAS is configured to always fail"),
    "Bad error message, got: {error}"
  );
}

fn new_byte_store(cas: &StubCAS) -> ByteStore {
  ByteStore::new(
    None,
    remote_options(
      cas.address(),
      10 * MEGABYTES,
      super::tests::STORE_BATCH_API_SIZE_LIMIT,
    ),
  )
  .unwrap()
}

async fn load_file_bytes(store: &ByteStore, digest: Digest) -> Result<Option<Bytes>, String> {
  store.load_bytes(digest).await
}
