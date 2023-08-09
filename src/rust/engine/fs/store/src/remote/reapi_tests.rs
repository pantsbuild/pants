// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use bytes::Bytes;
use grpc_util::tls;
use hashing::{Digest, Fingerprint};
use mock::StubCAS;
use testutil::data::TestData;

use crate::remote::{ByteStoreProvider, RemoteOptions};
use crate::tests::{big_file_bytes, big_file_fingerprint, new_cas};
use crate::MEGABYTES;

use super::reapi::Provider;
use super::ByteSource;

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

async fn new_provider(cas: &StubCAS) -> Provider {
  Provider::new(remote_options(
    cas.address(),
    10 * MEGABYTES,
    crate::tests::STORE_BATCH_API_SIZE_LIMIT,
  ))
  .await
  .unwrap()
}

fn byte_source(bytes: Bytes) -> ByteSource {
  Arc::new(move |r| bytes.slice(r))
}

async fn load_test(chunk_size: usize) {
  let testdata = TestData::roland();
  let cas = new_cas(chunk_size);

  let provider = new_provider(&cas).await;
  let mut destination = Vec::new();

  let found = provider
    .load(testdata.digest(), &mut destination)
    .await
    .unwrap();

  assert!(found);
  assert_eq!(destination, testdata.bytes());
}

#[tokio::test]
async fn load_existing_less_than_one_chunk() {
  load_test(TestData::roland().bytes().len() + 1).await;
}

#[tokio::test]
async fn load_existing_exactly_one_chunk() {
  load_test(TestData::roland().bytes().len()).await;
}

#[tokio::test]
async fn load_existing_multiple_chunks_exact() {
  load_test(1).await;
}

#[tokio::test]
async fn load_existing_multiple_chunks_nonfactor() {
  load_test(9).await;
}

#[tokio::test]
async fn load_missing() {
  let testdata = TestData::roland();
  let cas = StubCAS::empty();
  let provider = new_provider(&cas).await;
  let mut destination: Vec<u8> = Vec::new();

  let found = provider
    .load(testdata.digest(), &mut destination)
    .await
    .unwrap();

  assert!(!found);
  assert!(destination.is_empty());
}

#[tokio::test]
async fn load_grpc_error() {
  let testdata = TestData::roland();
  let cas = StubCAS::cas_always_errors();

  let provider = new_provider(&cas).await;
  let mut destination = Vec::new();

  let error = provider
    .load(testdata.digest(), &mut destination)
    .await
    .expect_err("Want error");

  assert!(
    error.contains("StubCAS is configured to always fail"),
    "Bad error message, got: {error}"
  )
}

#[tokio::test]
async fn load_existing_wrong_digest_error() {
  let testdata = TestData::roland();
  let cas = StubCAS::builder()
    .unverified_content(
      TestData::roland().fingerprint(),
      Bytes::from_static(b"not roland"),
    )
    .build();

  let provider = new_provider(&cas).await;
  let mut destination = Vec::new();

  let error = provider
    .load(testdata.digest(), &mut destination)
    .await
    .expect_err("Want error");

  assert!(
    error.contains("Remote CAS gave wrong digest"),
    "Bad error message, got: {error}"
  )
}

fn assert_cas_store(
  cas: &StubCAS,
  fingerprint: Fingerprint,
  bytes: Bytes,
  chunks: usize,
  chunk_size: usize,
) {
  let blobs = cas.blobs.lock();
  assert_eq!(blobs.get(&fingerprint), Some(&bytes));

  let write_message_sizes = cas.write_message_sizes.lock();
  assert_eq!(write_message_sizes.len(), chunks);
  for &size in write_message_sizes.iter() {
    assert!(
      size <= chunk_size,
      "Size {} should have been <= {}",
      size,
      chunk_size
    );
  }
}

#[tokio::test]
async fn store_bytes_one_chunk() {
  let testdata = TestData::roland();
  let cas = StubCAS::empty();
  let provider = new_provider(&cas).await;

  provider
    .store_bytes(testdata.digest(), byte_source(testdata.bytes()))
    .await
    .unwrap();

  assert_cas_store(&cas, testdata.fingerprint(), testdata.bytes(), 1, 1024)
}
#[tokio::test]
async fn store_bytes_multiple_chunks() {
  let cas = StubCAS::empty();
  let chunk_size = 10 * 1024;
  let provider = Provider::new(remote_options(
    cas.address(),
    chunk_size,
    0, // disable batch API, force streaming API
  ))
  .await
  .unwrap();

  let all_the_henries = big_file_bytes();
  let fingerprint = big_file_fingerprint();
  let digest = Digest::new(fingerprint, all_the_henries.len());

  provider
    .store_bytes(digest, byte_source(all_the_henries.clone()))
    .await
    .unwrap();

  assert_cas_store(&cas, fingerprint, all_the_henries, 98, chunk_size)
}

#[tokio::test]
async fn store_bytes_empty_file() {
  let testdata = TestData::empty();
  let cas = StubCAS::empty();
  let provider = new_provider(&cas).await;

  provider
    .store_bytes(testdata.digest(), byte_source(testdata.bytes()))
    .await
    .unwrap();

  assert_cas_store(&cas, testdata.fingerprint(), testdata.bytes(), 1, 1024)
}

#[tokio::test]
async fn store_bytes_grpc_error() {
  let testdata = TestData::roland();
  let cas = StubCAS::cas_always_errors();
  let provider = new_provider(&cas).await;

  let error = provider
    .store_bytes(testdata.digest(), byte_source(testdata.bytes()))
    .await
    .expect_err("Want err");
  assert!(
    error.contains("StubCAS is configured to always fail"),
    "Bad error message, got: {error}"
  );
}

#[tokio::test]
async fn store_bytes_connection_error() {
  let testdata = TestData::roland();
  let provider = Provider::new(remote_options(
    "http://doesnotexist.example".to_owned(),
    10 * MEGABYTES,
    crate::tests::STORE_BATCH_API_SIZE_LIMIT,
  ))
  .await
  .unwrap();

  let error = provider
    .store_bytes(testdata.digest(), byte_source(testdata.bytes()))
    .await
    .expect_err("Want err");
  assert!(
    error.contains("Unavailable: \"error trying to connect: dns error"),
    "Bad error message, got: {error}"
  );
}

#[tokio::test]
async fn list_missing_digests_none_missing() {
  let cas = new_cas(1024);

  let provider = new_provider(&cas).await;

  assert_eq!(
    provider
      .list_missing_digests(&mut vec![TestData::roland().digest()].into_iter())
      .await,
    Ok(HashSet::new())
  )
}

#[tokio::test]
async fn list_missing_digests_some_missing() {
  let cas = StubCAS::empty();

  let provider = new_provider(&cas).await;
  let digest = TestData::roland().digest();

  let mut digest_set = HashSet::new();
  digest_set.insert(digest);

  assert_eq!(
    provider
      .list_missing_digests(&mut vec![digest].into_iter())
      .await,
    Ok(digest_set)
  )
}

#[tokio::test]
async fn list_missing_digests_grpc_error() {
  let cas = StubCAS::cas_always_errors();
  let provider = new_provider(&cas).await;

  let error = provider
    .list_missing_digests(&mut vec![TestData::roland().digest()].into_iter())
    .await
    .expect_err("Want error");
  assert!(
    error.contains("StubCAS is configured to always fail"),
    "Bad error message, got: {error}"
  );
}
