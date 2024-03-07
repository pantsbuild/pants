// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

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
