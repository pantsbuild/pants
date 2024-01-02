// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(unused_must_use)]
// See https://github.com/hyperium/tonic/issues/1056
#![allow(clippy::derive_partial_eq_without_eq)]

mod conversions;
pub use conversions::require_digest;

#[cfg(test)]
mod conversions_tests;

pub mod gen {
    // NOTE: Prost automatically relies on the existence of this nested module structure because
    // it uses multiple `super` references (e.g., `super::super::super::Foo`) to traverse out of
    // a module to refer to protos in other modules.
    pub mod google {
        pub mod bytestream {
            tonic::include_proto!("google.bytestream");
        }
        pub mod longrunning {
            tonic::include_proto!("google.longrunning");
        }
        pub mod rpc {
            tonic::include_proto!("google.rpc");
        }
    }
    pub mod build {
        pub mod bazel {
            pub mod remote {
                pub mod execution {
                    pub mod v2 {
                        tonic::include_proto!("build.bazel.remote.execution.v2");

                        pub fn empty_digest() -> Digest {
                            Digest {
                hash: String::from(
                  "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                ),
                size_bytes: 0,
              }
                        }
                    }
                }
            }
            pub mod semver {
                tonic::include_proto!("build.bazel.semver");
            }
        }
    }
    pub mod buildbarn {
        pub mod cas {
            tonic::include_proto!("buildbarn.cas");
        }
    }
    pub mod pants {
        pub mod cache {
            tonic::include_proto!("pants.cache");
        }
    }
}

mod verification;
pub use crate::verification::verify_directory_canonical;
#[cfg(test)]
mod verification_tests;

mod hashing;
