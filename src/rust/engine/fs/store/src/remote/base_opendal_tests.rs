use opendal::{services::Memory, Operator};
use testutil::data::TestData;

use super::base_opendal::Provider;
use super::ByteStoreProvider;

const BASE: &str = "opendal-testing-base";

fn new_provider() -> Provider {
  let op = Operator::new(Memory::default()).unwrap().finish();
  Provider::new(op, BASE.to_owned())
}

#[tokio::test]
async fn load_existing() {
  let testdata = TestData::roland();
  let provider = new_provider();
  provider
    .op
    .write(
      &format!("{}/{}", BASE, testdata.fingerprint()),
      testdata.bytes(),
    )
    .await
    .unwrap();

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
