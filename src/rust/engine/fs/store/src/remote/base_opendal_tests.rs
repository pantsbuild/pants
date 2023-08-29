use std::collections::HashSet;

use opendal::{services::Memory, Operator};
use testutil::data::TestData;

use super::base_opendal::Provider;
use super::ByteStoreProvider;

const BASE: &str = "opendal-testing-base";

fn test_path(data: &TestData) -> String {
  format!("{}/{}", BASE, data.fingerprint())
}

fn new_provider() -> Provider {
  let op = Operator::new(Memory::default()).unwrap().finish();
  Provider::new(op, BASE.to_owned())
}

async fn write_test_data(provider: &Provider, data: &TestData) {
  provider
    .op
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
async fn store_bytes_data() {
  let testdata = TestData::roland();
  let provider = new_provider();

  provider
    .store_bytes(testdata.digest(), testdata.bytes())
    .await
    .unwrap();

  let result = provider
    .op
    .read(&format!("{}/{}", BASE, testdata.fingerprint()))
    .await
    .unwrap();
  assert_eq!(result, testdata.bytes());
}

#[tokio::test]
async fn store_bytes_empty() {
  let testdata = TestData::empty();
  let provider = new_provider();

  provider
    .store_bytes(testdata.digest(), testdata.bytes())
    .await
    .unwrap();

  let result = provider
    .op
    .read(&format!("{}/{}", BASE, testdata.fingerprint()))
    .await
    .unwrap();
  assert_eq!(result, testdata.bytes());
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
