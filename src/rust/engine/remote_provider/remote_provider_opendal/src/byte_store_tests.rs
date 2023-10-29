// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, HashSet};
use std::time::Duration;

use bytes::Bytes;
use grpc_util::tls;
use opendal::services::Memory;
use remote_provider_traits::{ByteStoreProvider, RemoteStoreOptions};
use testutil::data::TestData;
use testutil::file::mk_tempfile;

use crate::Provider;

const BASE: &str = "opendal-testing-base";

fn test_path(data: &TestData) -> String {
    let fingerprint = data.fingerprint().to_string();
    format!(
        "{}/{}/{}/{}",
        BASE,
        &fingerprint[0..2],
        &fingerprint[2..4],
        fingerprint
    )
}
fn remote_options() -> RemoteStoreOptions {
    RemoteStoreOptions {
        cas_address: "".to_owned(),
        instance_name: None,
        tls_config: tls::Config::default(),
        headers: BTreeMap::new(),
        chunk_size_bytes: 10000,
        rpc_timeout: Duration::from_secs(5),
        rpc_retries: 1,
        rpc_concurrency_limit: 256,
        batch_api_size_limit: 10000,
    }
}

fn new_provider() -> Provider {
    Provider::new(Memory::default(), BASE.to_owned(), remote_options()).unwrap()
}

async fn write_test_data(provider: &Provider, data: &TestData) {
    provider
        .operator
        .write(&test_path(&data), data.bytes())
        .await
        .unwrap();
}

#[tokio::test]
async fn load_existing() {
    let testdata = TestData::roland();
    let provider = new_provider();
    write_test_data(&provider, &testdata).await;

    let mut destination = Vec::new();
    let found = provider
        .load(testdata.digest(), &mut destination)
        .await
        .unwrap();
    assert!(found);
    assert_eq!(destination, testdata.bytes())
}

#[tokio::test]
async fn load_missing() {
    let testdata = TestData::roland();
    let provider = new_provider();

    let mut destination = Vec::new();
    let found = provider
        .load(testdata.digest(), &mut destination)
        .await
        .unwrap();
    assert!(!found);
    assert!(destination.is_empty())
}

#[tokio::test]
async fn load_empty() {
    // The empty file can be loaded even when it's not "physically" in the remote provider.
    let testdata = TestData::empty();
    let provider = new_provider();

    let mut destination = Vec::new();
    let found = provider
        .load(testdata.digest(), &mut destination)
        .await
        .unwrap();
    assert!(found);
    assert_eq!(destination, testdata.bytes());
}

#[tokio::test]
async fn load_existing_wrong_digest_eror() {
    let testdata = TestData::roland();
    let provider = new_provider();
    provider
        .operator
        .write(&test_path(&testdata), Bytes::from_static(b"not roland"))
        .await
        .unwrap();

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

#[tokio::test]
async fn load_without_validation_existing() {
    let testdata = TestData::roland();
    let bytes = Bytes::from_static(b"not roland");
    let provider = new_provider();
    provider
        .operator
        .write(&test_path(&testdata), bytes.clone())
        .await
        .unwrap();

    let mut destination = Vec::new();
    let found = provider
        .load_without_validation(testdata.digest(), &mut destination)
        .await
        .unwrap();
    assert!(found);
    assert_eq!(destination, bytes)
}

#[tokio::test]
async fn load_without_validation_missing() {
    let testdata = TestData::roland();
    let provider = new_provider();

    let mut destination = Vec::new();
    let found = provider
        .load_without_validation(testdata.digest(), &mut destination)
        .await
        .unwrap();
    assert!(!found);
    assert!(destination.is_empty())
}

async fn assert_store(provider: &Provider, testdata: &TestData) {
    let result = provider.operator.read(&test_path(testdata)).await.unwrap();
    assert_eq!(result, testdata.bytes());
}

#[tokio::test]
async fn store_bytes_data() {
    let testdata = TestData::roland();
    let provider = new_provider();

    provider
        .store_bytes(testdata.digest(), testdata.bytes())
        .await
        .unwrap();

    assert_store(&provider, &testdata).await;
}

#[tokio::test]
async fn store_bytes_empty() {
    let testdata = TestData::empty();
    let provider = new_provider();

    provider
        .store_bytes(testdata.digest(), testdata.bytes())
        .await
        .unwrap();

    // We don't actually store an empty file.
    assert!(!provider
        .operator
        .is_exist(&test_path(&testdata))
        .await
        .unwrap());
}

#[tokio::test]
async fn store_file_one_chunk() {
    let testdata = TestData::roland();
    let provider = new_provider();

    provider
        .store_file(
            testdata.digest(),
            mk_tempfile(Some(&testdata.bytes())).await,
        )
        .await
        .unwrap();
    assert_store(&provider, &testdata).await;
}

#[tokio::test]
async fn store_file_multiple_chunks() {
    let testdata = TestData::all_the_henries();
    let provider = new_provider();

    // Our current chunk size is the tokio::io::copy default (8KiB at
    // the time of writing).
    assert!(testdata.len() > 8 * 1024);

    provider
        .store_file(
            testdata.digest(),
            mk_tempfile(Some(&testdata.bytes())).await,
        )
        .await
        .unwrap();
    assert_store(&provider, &testdata).await;
}

#[tokio::test]
async fn store_file_empty_file() {
    let testdata = TestData::empty();
    let provider = new_provider();

    provider
        .store_file(
            testdata.digest(),
            mk_tempfile(Some(&testdata.bytes())).await,
        )
        .await
        .unwrap();

    // We don't actually store an empty file.
    assert!(!provider
        .operator
        .is_exist(&test_path(&testdata))
        .await
        .unwrap());
}

#[tokio::test]
async fn list_missing_digests_none_missing() {
    let testdata = TestData::roland();
    let provider = new_provider();
    write_test_data(&provider, &testdata).await;

    assert_eq!(
        provider
            .list_missing_digests(&mut vec![testdata.digest()].into_iter())
            .await,
        Ok(HashSet::new())
    )
}

#[tokio::test]
async fn list_missing_digests_some_missing() {
    let testdata = TestData::roland();
    let digest = testdata.digest();

    let provider = new_provider();

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
async fn list_missing_digests_empty_never_missing() {
    let testdata = TestData::empty();
    let provider = new_provider();

    assert_eq!(
        provider
            .list_missing_digests(&mut vec![testdata.digest()].into_iter())
            .await,
        Ok(HashSet::new())
    )
}
