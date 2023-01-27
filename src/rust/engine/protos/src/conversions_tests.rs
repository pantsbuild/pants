// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::convert::TryInto;

use crate::gen::build::bazel::remote::execution::v2 as remexec;

#[test]
fn from_our_digest() {
  let our_digest = &hashing::Digest::new(
    hashing::Fingerprint::from_hex_string(
      "0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff",
    )
    .unwrap(),
    10,
  );
  let converted: remexec::Digest = our_digest.into();
  let want = remexec::Digest {
    hash: "0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff".to_owned(),
    size_bytes: 10,
  };
  assert_eq!(converted, want);
}

#[test]
fn from_bazel_digest() {
  let bazel_digest = remexec::Digest {
    hash: "0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff".to_owned(),
    size_bytes: 10,
  };
  let converted: Result<hashing::Digest, String> = (&bazel_digest).try_into();
  let want = hashing::Digest::new(
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
  let bazel_digest = remexec::Digest {
    hash: "0".to_owned(),
    size_bytes: 10,
  };
  let converted: Result<hashing::Digest, String> = (&bazel_digest).try_into();
  let err = converted.expect_err("Want Err converting bad digest");
  assert!(
    err.starts_with("Bad fingerprint in Digest \"0\":"),
    "Bad error message: {err}"
  );
}
