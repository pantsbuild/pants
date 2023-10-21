// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::Arc;
use std::time::Duration;

use bytes::Bytes;
use grpc_util::tls;
use hashing::{Digest, Fingerprint};
use parking_lot::Mutex;
use remote_provider::{ByteStoreProvider, LoadDestination, RemoteOptions};
use tempfile::TempDir;
use testutil::data::TestData;
use testutil::file::mk_tempfile;
use tokio::fs::File;
use tokio::io::{AsyncReadExt, AsyncSeekExt, AsyncWriteExt};
use workunit_store::WorkunitStore;

use crate::remote::ByteStore;
use crate::tests::new_cas;
use crate::MEGABYTES;

#[tokio::test]
async fn smoke_test_from_options_reapi_provider() {
    // This runs through the various methods using the 'real' REAPI provider (talking to a stubbed
    // CAS), as a double-check that the test provider is plausible and test provider selection works.
    let roland = TestData::roland();
    let empty = TestData::empty();

    let cas = new_cas(10);

    let store = ByteStore::from_options(RemoteOptions {
        cas_address: cas.address(),
        instance_name: None,
        tls_config: tls::Config::default(),
        headers: BTreeMap::new(),
        chunk_size_bytes: 10 * MEGABYTES,
        rpc_timeout: Duration::from_secs(5),
        rpc_retries: 1,
        rpc_concurrency_limit: 256,
        capabilities_cell_opt: None,
        batch_api_size_limit: crate::tests::STORE_BATCH_API_SIZE_LIMIT,
    })
    .await
    .unwrap();

    let mut missing_set = HashSet::new();
    missing_set.insert(empty.digest());

    // Only roland is in the CAS:
    assert_eq!(
        store.load_bytes(roland.digest()).await,
        Ok(Some(roland.bytes()))
    );
    assert_eq!(store.load_bytes(empty.digest()).await, Ok(None));
    assert_eq!(
        store
            .list_missing_digests(vec![roland.digest(), empty.digest()])
            .await,
        Ok(missing_set)
    );

    // Insert empty:
    assert_eq!(store.store_bytes(empty.bytes()).await, Ok(()));
    assert_eq!(
        store.load_bytes(empty.digest()).await,
        Ok(Some(empty.bytes()))
    );
}

#[tokio::test]
async fn smoke_test_from_options_file_provider() {
    // This runs through the various methods using the file:// provider, as a double-check that the
    // test provider is plausible and test provider selection works.
    let roland = TestData::roland();
    let catnip = TestData::catnip();

    let _ = WorkunitStore::setup_for_tests();
    let dir = TempDir::new().unwrap();

    let store = ByteStore::from_options(RemoteOptions {
        cas_address: format!("file://{}", dir.path().display()),
        instance_name: None,
        tls_config: tls::Config::default(),
        headers: BTreeMap::new(),
        chunk_size_bytes: 10 * MEGABYTES,
        rpc_timeout: Duration::from_secs(5),
        rpc_retries: 1,
        rpc_concurrency_limit: 256,
        capabilities_cell_opt: None,
        batch_api_size_limit: crate::tests::STORE_BATCH_API_SIZE_LIMIT,
    })
    .await
    .unwrap();

    let mut missing_set = HashSet::new();
    missing_set.insert(catnip.digest());

    // Insert roland:
    assert_eq!(store.store_bytes(roland.bytes()).await, Ok(()));
    assert_eq!(
        store.load_bytes(roland.digest()).await,
        Ok(Some(roland.bytes()))
    );
    // Only roland is stored:
    assert_eq!(store.load_bytes(catnip.digest()).await, Ok(None));
    assert_eq!(
        store
            .list_missing_digests(vec![roland.digest(), catnip.digest()])
            .await,
        Ok(missing_set)
    );

    // Insert catnip:
    assert_eq!(store.store_bytes(catnip.bytes()).await, Ok(()));
    assert_eq!(
        store.load_bytes(catnip.digest()).await,
        Ok(Some(catnip.bytes()))
    );
}

#[tokio::test]
async fn load_bytes_existing() {
    let _ = WorkunitStore::setup_for_tests();
    let testdata = TestData::roland();
    let store = new_byte_store(&testdata);

    assert_eq!(
        store.load_bytes(testdata.digest()).await,
        Ok(Some(testdata.bytes()))
    );
}

#[tokio::test]
async fn load_bytes_missing() {
    let _ = WorkunitStore::setup_for_tests();
    let (store, _) = empty_byte_store();

    assert_eq!(
        store.load_bytes(TestData::roland().digest()).await,
        Ok(None)
    );
}

#[tokio::test]
async fn load_bytes_provider_error() {
    let _ = WorkunitStore::setup_for_tests();
    let store = byte_store_always_error_provider();

    assert_error(store.load_bytes(TestData::roland().digest()).await);
}

#[tokio::test]
async fn load_file_existing() {
    // 5MB of data
    let testdata = TestData::new(&"12345".repeat(MEGABYTES));

    let _ = WorkunitStore::setup_for_tests();
    let store = new_byte_store(&testdata);

    let file = mk_tempfile(None).await;

    let file = store
        .load_file(testdata.digest(), file)
        .await
        .unwrap()
        .unwrap();

    assert_file_contents(file, &testdata.string()).await;
}

#[tokio::test]
async fn load_file_missing() {
    let _ = WorkunitStore::setup_for_tests();
    let (store, _) = empty_byte_store();

    let file = mk_tempfile(None).await;

    let result = store.load_file(TestData::roland().digest(), file).await;
    assert!(result.unwrap().is_none());
}

#[tokio::test]
async fn load_file_provider_error() {
    let _ = WorkunitStore::setup_for_tests();
    let store = byte_store_always_error_provider();

    let file = mk_tempfile(None).await;

    assert_error(store.load_file(TestData::roland().digest(), file).await);
}

#[tokio::test]
async fn store_bytes() {
    let _ = WorkunitStore::setup_for_tests();
    let testdata = TestData::roland();

    let (store, provider) = empty_byte_store();
    assert_eq!(store.store_bytes(testdata.bytes()).await, Ok(()));

    let blobs = provider.blobs.lock();
    assert_eq!(blobs.get(&testdata.fingerprint()), Some(&testdata.bytes()));
}

#[tokio::test]
async fn store_bytes_provider_error() {
    let _ = WorkunitStore::setup_for_tests();
    let store = byte_store_always_error_provider();
    assert_error(store.store_bytes(TestData::roland().bytes()).await)
}

#[tokio::test]
async fn store_file() {
    let _ = WorkunitStore::setup_for_tests();
    let testdata = TestData::roland();

    let (store, provider) = empty_byte_store();
    assert_eq!(
        store
            .store_file(
                testdata.digest(),
                mk_tempfile(Some(&testdata.bytes())).await
            )
            .await,
        Ok(())
    );

    let blobs = provider.blobs.lock();
    assert_eq!(blobs.get(&testdata.fingerprint()), Some(&testdata.bytes()));
}

#[tokio::test]
async fn store_file_provider_error() {
    let _ = WorkunitStore::setup_for_tests();
    let testdata = TestData::roland();
    let store = byte_store_always_error_provider();
    assert_error(
        store
            .store_file(
                testdata.digest(),
                mk_tempfile(Some(&testdata.bytes())).await,
            )
            .await,
    );
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
async fn list_missing_digests_provider_error() {
    let _ = WorkunitStore::setup_for_tests();
    let store = byte_store_always_error_provider();

    assert_error(
        store
            .list_missing_digests(vec![TestData::roland().digest()])
            .await,
    )
}

#[tokio::test]
async fn file_as_load_destination_reset() {
    let mut file = mk_tempfile(Some(b"initial")).await;

    file.reset().await.unwrap();
    assert_file_contents(file, "").await;
}

#[tokio::test]
async fn vec_as_load_destination_reset() {
    let mut vec: Vec<u8> = b"initial".to_vec();

    vec.reset().await.unwrap();
    assert!(vec.is_empty());
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

async fn assert_file_contents(mut file: tokio::fs::File, expected: &str) {
    file.rewind().await.unwrap();

    let mut buf = String::new();
    file.read_to_string(&mut buf).await.unwrap();
    assert_eq!(buf.len(), expected.len());
    // (assert_eq! means failures unhelpfully print a potentially-huge string)
    assert!(buf == expected);
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
        self.blobs
            .lock()
            .insert(Digest::of_bytes(&bytes).hash, bytes);
    }
}

#[async_trait::async_trait]
impl ByteStoreProvider for TestProvider {
    async fn store_bytes(&self, digest: Digest, bytes: Bytes) -> Result<(), String> {
        self.blobs.lock().insert(digest.hash, bytes);
        Ok(())
    }

    async fn store_file(&self, digest: Digest, mut file: File) -> Result<(), String> {
        // just pull it all into memory
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes).await.unwrap();
        self.blobs.lock().insert(digest.hash, Bytes::from(bytes));
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
}

struct AlwaysErrorProvider;
impl AlwaysErrorProvider {
    fn new() -> Arc<AlwaysErrorProvider> {
        Arc::new(AlwaysErrorProvider)
    }
}
#[async_trait::async_trait]
impl ByteStoreProvider for AlwaysErrorProvider {
    async fn store_bytes(&self, _: Digest, _: Bytes) -> Result<(), String> {
        Err("AlwaysErrorProvider always fails".to_owned())
    }

    async fn store_file(&self, _: Digest, _: File) -> Result<(), String> {
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
}
