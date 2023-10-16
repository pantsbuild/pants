use std::collections::{BTreeMap, HashSet};
use std::time::Duration;

use bytes::Bytes;
use grpc_util::tls;
use hashing::Digest;
use mock::StubCAS;
use testutil::data::{TestData, TestDirectory};
use workunit_store::WorkunitStore;

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
    let _ = WorkunitStore::setup_for_tests();
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
    let _ = WorkunitStore::setup_for_tests();
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
    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::cas_always_errors();

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
    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::cas_always_errors();

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
    let _ = WorkunitStore::setup_for_tests();
    let testdata = TestData::roland();
    let cas = StubCAS::empty();

    let store = new_byte_store(&cas);
    assert_eq!(store.store_bytes(testdata.bytes()).await, Ok(()));

    let blobs = cas.blobs.lock();
    assert_eq!(blobs.get(&testdata.fingerprint()), Some(&testdata.bytes()));
}

#[tokio::test]
async fn write_file_multiple_chunks() {
    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::empty();

    let store = ByteStore::new(
        &cas.address(),
        None,
        tls::Config::default(),
        BTreeMap::new(),
        10 * 1024,
        Duration::from_secs(5),
        1,
        256,
        None,
        0, // disable batch API, force streaming API
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
    let _ = WorkunitStore::setup_for_tests();
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
    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::cas_always_errors();

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
        tls::Config::default(),
        BTreeMap::new(),
        10 * 1024 * 1024,
        Duration::from_secs(1),
        1,
        256,
        None,
        super::tests::STORE_BATCH_API_SIZE_LIMIT,
    )
    .unwrap();
    let error = store
        .store_bytes(TestData::roland().bytes())
        .await
        .expect_err("Want error");
    assert!(
        error.contains("Unavailable: \"error trying to connect: dns error"),
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
                store.find_missing_blobs_request(vec![TestData::roland().digest()]),
            )
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
        store
            .list_missing_digests(store.find_missing_blobs_request(vec![digest]))
            .await,
        Ok(digest_set)
    );
}

#[tokio::test]
async fn list_missing_digests_error() {
    let _ = WorkunitStore::setup_for_tests();
    let cas = StubCAS::cas_always_errors();

    let store = new_byte_store(&cas);

    let error = store
        .list_missing_digests(store.find_missing_blobs_request(vec![TestData::roland().digest()]))
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
        tls::Config::default(),
        BTreeMap::new(),
        10 * MEGABYTES,
        Duration::from_secs(1),
        1,
        256,
        None,
        super::tests::STORE_BATCH_API_SIZE_LIMIT,
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
    store
        .load_bytes_with(digest, |b| Ok(b))
        .await
        .map_err(|err| format!("{}", err))
}
