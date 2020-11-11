use std::convert::TryInto;

use hashing;

#[test]
fn from_our_digest() {
  let our_digest = &hashing::Digest(
    hashing::Fingerprint::from_hex_string(
      "0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff",
    )
    .unwrap(),
    10,
  );
  let converted: crate::remote_execution::Digest = our_digest.into();
  let mut want = crate::remote_execution::Digest::new();
  want.set_hash("0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff".to_owned());
  want.set_size_bytes(10);
  assert_eq!(converted, want);
}

#[test]
fn from_bazel_digest() {
  let mut bazel_digest = crate::remote_execution::Digest::new();
  bazel_digest
    .set_hash("0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff".to_owned());
  bazel_digest.set_size_bytes(10);
  let converted: Result<hashing::Digest, String> = (&bazel_digest).try_into();
  let want = hashing::Digest(
    hashing::Fingerprint::from_hex_string(
      "0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff",
    )
    .unwrap(),
    10,
  );
  assert_eq!(converted, Ok(want));
}

#[test]
fn from_bad_bazel_digest() {
  let mut bazel_digest = crate::remote_execution::Digest::new();
  bazel_digest.set_hash("0".to_owned());
  bazel_digest.set_size_bytes(10);
  let converted: Result<hashing::Digest, String> = (&bazel_digest).try_into();
  let err = converted.expect_err("Want Err converting bad digest");
  assert!(
    err.starts_with("Bad fingerprint in Digest \"0\":"),
    "Bad error message: {}",
    err
  );
}
