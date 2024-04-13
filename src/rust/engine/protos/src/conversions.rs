// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
impl<'a> From<&'a hashing::Digest> for crate::gen::build::bazel::remote::execution::v2::Digest {
    fn from(d: &'a hashing::Digest) -> Self {
        Self {
            hash: d.hash.to_hex(),
            size_bytes: d.size_bytes as i64,
        }
    }
}

impl From<hashing::Digest> for crate::gen::build::bazel::remote::execution::v2::Digest {
    fn from(d: hashing::Digest) -> Self {
        Self {
            hash: d.hash.to_hex(),
            size_bytes: d.size_bytes as i64,
        }
    }
}

impl<'a> TryFrom<&'a crate::gen::build::bazel::remote::execution::v2::Digest> for hashing::Digest {
    type Error = String;

    fn try_from(
        d: &crate::gen::build::bazel::remote::execution::v2::Digest,
    ) -> Result<Self, Self::Error> {
        hashing::Fingerprint::from_hex_string(&d.hash)
            .map_err(|err| format!("Bad fingerprint in Digest {:?}: {:?}", &d.hash, err))
            .map(|fingerprint| hashing::Digest::new(fingerprint, d.size_bytes as usize))
    }
}

impl TryFrom<crate::gen::build::bazel::remote::execution::v2::Digest> for hashing::Digest {
    type Error = String;

    fn try_from(
        d: crate::gen::build::bazel::remote::execution::v2::Digest,
    ) -> Result<Self, Self::Error> {
        hashing::Fingerprint::from_hex_string(&d.hash)
            .map_err(|err| format!("Bad fingerprint in Digest {:?}: {:?}", &d.hash, err))
            .map(|fingerprint| hashing::Digest::new(fingerprint, d.size_bytes as usize))
    }
}

pub fn require_digest<
    'a,
    D: Into<Option<&'a crate::gen::build::bazel::remote::execution::v2::Digest>>,
>(
    digest_opt: D,
) -> Result<hashing::Digest, String> {
    match digest_opt.into() {
        Some(digest) => hashing::Digest::try_from(digest),
        None => {
            Err("Protocol violation: Digest missing from a Remote Execution API protobuf.".into())
        }
    }
}
