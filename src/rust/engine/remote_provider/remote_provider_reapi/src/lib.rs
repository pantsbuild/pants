// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
    clippy::all,
    clippy::default_trait_access,
    clippy::expl_impl_clone_on_copy,
    clippy::if_not_else,
    clippy::needless_continue,
    clippy::unseparated_literal_suffix,
    clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
    clippy::len_without_is_empty,
    clippy::redundant_field_names,
    clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use protos::gen::build::bazel::remote::execution::v2 as remexec;
use tonic::metadata::BinaryMetadataValue;
use tonic::Request;

use grpc_util::prost::MessageExt;

pub mod action_cache;
#[cfg(test)]
pub mod action_cache_tests;
pub mod byte_store;
#[cfg(test)]
pub mod byte_store_tests;

/// Apply REAPI request metadata header to a `tonic::Request`.
pub fn apply_headers<T>(mut request: Request<T>, build_id: &str) -> Request<T> {
    let reapi_request_metadata = remexec::RequestMetadata {
        tool_details: Some(remexec::ToolDetails {
            tool_name: "pants".into(),
            ..remexec::ToolDetails::default()
        }),
        tool_invocation_id: build_id.to_string(),
        ..remexec::RequestMetadata::default()
    };

    let md = request.metadata_mut();
    md.insert_bin(
        "google.devtools.remoteexecution.v1test.requestmetadata-bin",
        BinaryMetadataValue::try_from(reapi_request_metadata.to_bytes()).unwrap(),
    );

    request
}
