use super::base_opendal::Provider;
use super::ByteStoreProvider;
use opendal::{services::Memory, Operator};
use testutil::data::TestData;

const BASE: &str = "opendal-testing-base";

fn new_provider() -> Provider {
  let op = Operator::new(Memory::default()).unwrap().finish();
  Provider::new(op, BASE.to_owned())
}

#[tokio::test]
async fn load_existing_less_than_one_chunk() {
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
