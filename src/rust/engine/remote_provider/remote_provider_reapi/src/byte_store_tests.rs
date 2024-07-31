// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, HashSet};
use std::time::Duration;

use bytes::Bytes;
use grpc_util::tls;
use mock::{RequestType, StubCAS};
use tempfile::TempDir;
use testutil::data::TestData;
use testutil::file::mk_tempfile;
use tokio::fs::File;
use workunit_store::WorkunitStore;

use remote_provider_traits::{
    ByteStoreProvider, ListMissingDigestsAssurance, RemoteProvider, RemoteStoreOptions,
};

use crate::byte_store::Provider;

const MEGABYTES: usize = 1024 * 1024;
const STORE_BATCH_API_SIZE_LIMIT: usize = 4 * MEGABYTES;

fn remote_options(
    store_address: String,
    chunk_size_bytes: usize,
    batch_api_size_limit: usize,
) -> RemoteStoreOptions {
    RemoteStoreOptions {
        provider: RemoteProvider::Reapi,
        store_address,
        instance_name: None,
        tls_config: tls::Config::default(),
        headers: BTreeMap::new(),
        chunk_size_bytes,
        timeout: Duration::from_secs(5),
        retries: 1,
        concurrency_limit: 256,
        batch_api_size_limit,
    }
}

async fn new_provider(cas: &StubCAS) -> Provider {
    Provider::new(remote_options(
        cas.address(),
        10 * MEGABYTES,
        STORE_BATCH_API_SIZE_LIMIT,
    ))
    .await
    .unwrap()
}

async fn load_test(chunk_size: usize) {
    let _ = WorkunitStore::setup_for_tests();
    let testdata = TestData::roland();
    let cas = StubCAS::builder()
        .chunk_size_bytes(chunk_size)
        .file(&testdata)
        .build();

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
    );
    // retries:
    assert_eq!(
        cas.request_counts.lock().get(&RequestType::BSRead),
        Some(&3)
    );
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

fn assert_cas_store(cas: &StubCAS, testdata: &TestData, chunks: usize, chunk_size: usize) {
    let blobs = cas.blobs.lock();
    assert_eq!(blobs.get(&testdata.fingerprint()), Some(&testdata.bytes()));

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
async fn store_file_one_chunk() {
    let testdata = TestData::roland();
    let cas = StubCAS::empty();
    let provider = new_provider(&cas).await;

    provider
        .store_file(
            testdata.digest(),
            mk_tempfile(Some(&testdata.bytes())).await,
        )
        .await
        .unwrap();

    assert_cas_store(&cas, &testdata, 1, 1024)
}
#[tokio::test]
async fn store_file_multiple_chunks() {
    let testdata = TestData::all_the_henries();

    let cas = StubCAS::empty();
    let chunk_size = 10 * 1024;
    let provider = Provider::new(remote_options(
        cas.address(),
        chunk_size,
        0, // disable batch API, force streaming API
    ))
    .await
    .unwrap();

    provider
        .store_file(
            testdata.digest(),
            mk_tempfile(Some(&testdata.bytes())).await,
        )
        .await
        .unwrap();

    assert_cas_store(&cas, &testdata, 98, chunk_size)
}

#[tokio::test]
async fn store_file_empty_file() {
    let testdata = TestData::empty();
    let cas = StubCAS::empty();
    let provider = new_provider(&cas).await;

    provider
        .store_file(
            testdata.digest(),
            mk_tempfile(Some(&testdata.bytes())).await,
        )
        .await
        .unwrap();

    assert_cas_store(&cas, &testdata, 1, 1024)
}

#[tokio::test]
async fn store_file_grpc_error() {
    let testdata = TestData::roland();
    let cas = StubCAS::cas_always_errors();
    let provider = new_provider(&cas).await;

    let error = provider
        .store_file(
            testdata.digest(),
            mk_tempfile(Some(&testdata.bytes())).await,
        )
        .await
        .expect_err("Want err");
    assert!(
        error.contains("StubCAS is configured to always fail"),
        "Bad error message, got: {error}"
    );

    // retries:
    assert_eq!(
        cas.request_counts.lock().get(&RequestType::BSWrite),
        Some(&3)
    );
}

#[tokio::test]
async fn store_file_connection_error() {
    let testdata = TestData::roland();
    let provider = Provider::new(remote_options(
        "http://doesnotexist.example".to_owned(),
        10 * MEGABYTES,
        STORE_BATCH_API_SIZE_LIMIT,
    ))
    .await
    .unwrap();

    let error = provider
        .store_file(
            testdata.digest(),
            mk_tempfile(Some(&testdata.bytes())).await,
        )
        .await
        .expect_err("Want err");
    assert!(
        error.contains("Unavailable: \"error trying to connect: dns error"),
        "Bad error message, got: {error}"
    );
}

#[tokio::test]
async fn store_file_source_read_error_immediately() {
    let testdata = TestData::roland();
    let cas = StubCAS::empty();
    let provider = new_provider(&cas).await;

    let temp_dir = TempDir::new().unwrap();
    let file_that_is_a_dir = File::open(temp_dir.path()).await.unwrap();

    let error = provider
        .store_file(testdata.digest(), file_that_is_a_dir)
        .await
        .expect_err("Want err");
    assert!(
        error.contains("Is a directory"),
        "Bad error message, got: {error}",
    )
}

// TODO: it would also be good to validate the behaviour if the file reads start failing later
// (e.g. read 10 bytes, and then fail), if that's a thing that is possible.

#[tokio::test]
async fn store_bytes_one_chunk() {
    let testdata = TestData::roland();
    let cas = StubCAS::empty();
    let provider = new_provider(&cas).await;

    provider
        .store_bytes(testdata.digest(), testdata.bytes())
        .await
        .unwrap();

    assert_cas_store(&cas, &testdata, 1, 1024)
}
#[tokio::test]
async fn store_bytes_multiple_chunks() {
    let testdata = TestData::all_the_henries();

    let cas = StubCAS::empty();
    let chunk_size = 10 * 1024;
    let provider = Provider::new(remote_options(
        cas.address(),
        chunk_size,
        0, // disable batch API, force streaming API
    ))
    .await
    .unwrap();

    provider
        .store_bytes(testdata.digest(), testdata.bytes())
        .await
        .unwrap();

    assert_cas_store(&cas, &testdata, 98, chunk_size)
}

#[tokio::test]
async fn store_bytes_empty_file() {
    let testdata = TestData::empty();
    let cas = StubCAS::empty();
    let provider = new_provider(&cas).await;

    provider
        .store_bytes(testdata.digest(), testdata.bytes())
        .await
        .unwrap();

    assert_cas_store(&cas, &testdata, 1, 1024)
}

#[tokio::test]
async fn store_bytes_batch_grpc_error() {
    let testdata = TestData::roland();
    let cas = StubCAS::cas_always_errors();
    let provider = new_provider(&cas).await;

    let error = provider
        .store_bytes(testdata.digest(), testdata.bytes())
        .await
        .expect_err("Want err");
    assert!(
        error.contains("StubCAS is configured to always fail"),
        "Bad error message, got: {error}"
    );

    // retries:
    assert_eq!(
        cas.request_counts
            .lock()
            .get(&RequestType::CASBatchUpdateBlobs),
        Some(&3)
    );
}

#[tokio::test]
async fn store_bytes_write_stream_grpc_error() {
    let testdata = TestData::all_the_henries();
    let cas = StubCAS::cas_always_errors();
    let chunk_size = 10 * 1024;
    let provider = Provider::new(remote_options(
        cas.address(),
        chunk_size,
        0, // disable batch API, force streaming API
    ))
    .await
    .unwrap();

    let error = provider
        .store_bytes(testdata.digest(), testdata.bytes())
        .await
        .expect_err("Want err");
    assert!(
        error.contains("StubCAS is configured to always fail"),
        "Bad error message, got: {error}"
    );

    // retries:
    assert_eq!(
        cas.request_counts.lock().get(&RequestType::BSWrite),
        Some(&3)
    );
}

#[tokio::test]
async fn store_bytes_connection_error() {
    let testdata = TestData::roland();
    let provider = Provider::new(remote_options(
        "http://doesnotexist.example".to_owned(),
        10 * MEGABYTES,
        STORE_BATCH_API_SIZE_LIMIT,
    ))
    .await
    .unwrap();

    let error = provider
        .store_bytes(testdata.digest(), testdata.bytes())
        .await
        .expect_err("Want err");
    assert!(
        error.contains("Unavailable: \"error trying to connect: dns error"),
        "Bad error message, got: {error}"
    );
}

#[tokio::test]
async fn list_missing_digests_none_missing() {
    let testdata = TestData::roland();
    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::builder().file(&testdata).build();

    let provider = new_provider(&cas).await;

    for assurance in [
        // both assurances behave the same
        ListMissingDigestsAssurance::ConfirmExistence,
        ListMissingDigestsAssurance::AllowFalsePositives,
    ] {
        assert_eq!(
            provider
                .list_missing_digests(&mut vec![testdata.digest()].into_iter(), assurance)
                .await,
            Ok(HashSet::new())
        )
    }
}

#[tokio::test]
async fn list_missing_digests_some_missing() {
    let cas = StubCAS::empty();

    let provider = new_provider(&cas).await;
    let digest = TestData::roland().digest();

    let mut digest_set = HashSet::new();
    digest_set.insert(digest);

    for assurance in [
        // both assurances behave the same
        ListMissingDigestsAssurance::ConfirmExistence,
        ListMissingDigestsAssurance::AllowFalsePositives,
    ] {
        assert_eq!(
            provider
                .list_missing_digests(&mut vec![digest].into_iter(), assurance)
                .await,
            Ok(digest_set.clone())
        )
    }
}

#[tokio::test]
async fn list_missing_digests_grpc_error() {
    let cas = StubCAS::cas_always_errors();
    let provider = new_provider(&cas).await;

    for assurance in [
        // both assurances behave the same
        ListMissingDigestsAssurance::ConfirmExistence,
        ListMissingDigestsAssurance::AllowFalsePositives,
    ] {
        let error = provider
            .list_missing_digests(
                &mut vec![TestData::roland().digest()].into_iter(),
                assurance,
            )
            .await
            .expect_err("Want error");
        assert!(
            error.contains("StubCAS is configured to always fail"),
            "Bad error message, got: {error}"
        );
        // retries:
        assert_eq!(
            cas.request_counts
                .lock()
                .get(&RequestType::CASFindMissingBlobs),
            Some(&3)
        );
    }
}
