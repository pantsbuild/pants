use hashing;

impl<'a> From<&'a hashing::Digest> for super::remote_execution::Digest {
  fn from(d: &hashing::Digest) -> Self {
    let mut digest = super::remote_execution::Digest::new();
    digest.set_hash(d.0.to_hex());
    digest.set_size_bytes(d.1 as i64);
    digest
  }
}

impl<'a> From<&'a super::remote_execution::Digest> for hashing::Digest {
  fn from(d: &super::remote_execution::Digest) -> Self {
    hashing::Digest(
      hashing::Fingerprint::from_hex_string(d.get_hash()).expect("Bad fingerprint in Digest"),
      d.get_size_bytes() as usize,
    )
  }
}

#[cfg(test)]
mod tests {
  use hashing;

  #[test]
  fn from_our_digest() {
    let our_digest = &hashing::Digest(
      hashing::Fingerprint::from_hex_string(
        "0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff",
      ).unwrap(),
      10,
    );
    let converted: super::super::remote_execution::Digest = our_digest.into();
    let mut want = super::super::remote_execution::Digest::new();
    want.set_hash("0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff".to_owned());
    want.set_size_bytes(10);
    assert_eq!(converted, want);
  }

  #[test]
  fn from_bazel_digest() {
    let mut bazel_digest = super::super::remote_execution::Digest::new();
    bazel_digest
      .set_hash("0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff".to_owned());
    bazel_digest.set_size_bytes(10);
    let converted: hashing::Digest = (&bazel_digest).into();
    let want = hashing::Digest(
      hashing::Fingerprint::from_hex_string(
        "0123456789abcdeffedcba98765432100000000000000000ffffffffffffffff",
      ).unwrap(),
      10,
    );
    assert_eq!(converted, want);
  }
}
