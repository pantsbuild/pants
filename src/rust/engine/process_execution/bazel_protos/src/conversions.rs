use hashing;

impl<'a> From<&'a hashing::Digest> for crate::remote_execution::Digest {
  fn from(d: &hashing::Digest) -> Self {
    let mut digest = super::remote_execution::Digest::new();
    digest.set_hash(d.0.to_hex());
    digest.set_size_bytes(d.1 as i64);
    digest
  }
}

impl<'a> From<&'a hashing::Digest> for crate::build::bazel::remote::execution::v2::Digest {
  fn from(d: &hashing::Digest) -> Self {
    Self {
      hash: d.0.to_hex(),
      size_bytes: d.1 as i64,
    }
  }
}

impl<'a> From<&'a super::remote_execution::Digest> for Result<hashing::Digest, String> {
  fn from(d: &super::remote_execution::Digest) -> Self {
    hashing::Fingerprint::from_hex_string(d.get_hash())
      .map_err(|err| format!("Bad fingerprint in Digest {:?}: {:?}", d.get_hash(), err))
      .map(|fingerprint| hashing::Digest(fingerprint, d.get_size_bytes() as usize))
  }
}

impl From<crate::google::longrunning::Operation> for crate::operations::Operation {
  fn from(op: crate::google::longrunning::Operation) -> Self {
    let mut dst = Self::new();
    dst.set_name(op.name);
    dst.set_metadata(prost_any_to_gcprio_any(op.metadata.unwrap()));
    dst.set_done(op.done);
    match op.result {
      Some(crate::google::longrunning::operation::Result::Response(response)) => {
        dst.set_response(prost_any_to_gcprio_any(response))
      }
      Some(crate::google::longrunning::operation::Result::Error(status)) => {
        dst.set_error(prost_status_to_gcprio_status(status))
      }
      None => {}
    };
    dst
  }
}

pub fn prost_any_to_gcprio_any(any: prost_types::Any) -> protobuf::well_known_types::Any {
  let prost_types::Any { type_url, value } = any;
  let mut dst = protobuf::well_known_types::Any::new();
  dst.set_type_url(type_url);
  dst.set_value(value);
  dst
}

pub fn prost_status_to_gcprio_status(status: crate::google::rpc::Status) -> crate::status::Status {
  let crate::google::rpc::Status {
    code,
    message,
    details,
  } = status;
  let mut dst = crate::status::Status::new();
  dst.set_code(code);
  dst.set_message(message);
  dst.set_details(
    details
      .into_iter()
      .map(prost_any_to_gcprio_any)
      .collect::<Vec<_>>()
      .into(),
  );
  dst
}

#[cfg(test)]
mod tests {
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
    let converted: Result<hashing::Digest, String> = (&bazel_digest).into();
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
    let mut bazel_digest = super::super::remote_execution::Digest::new();
    bazel_digest.set_hash("0".to_owned());
    bazel_digest.set_size_bytes(10);
    let converted: Result<hashing::Digest, String> = (&bazel_digest).into();
    let err = converted.expect_err("Want Err converting bad digest");
    assert!(
      err.starts_with("Bad fingerprint in Digest \"0\":"),
      "Bad error message: {}",
      err
    );
  }
}
