use std::collections::BTreeMap;

use bytes::BytesMut;
use prost::Message;
use tonic::metadata::{MetadataMap, MetadataValue};

use crate::gen::build::bazel::remote::execution::v2 as remote_execution;

pub fn call_option(
  headers: &'static BTreeMap<String, String>,
  build_id: Option<String>,
) -> Result<MetadataMap, String> {
  let mut grpc_headers = MetadataMap::with_capacity(headers.len() + 1);
  for (header_name, header_value) in headers {
    let value = MetadataValue::from_str(header_value.as_str())
      .map_err(|err| format!("Error setting header {}: {}", header_name, err))?;
    grpc_headers.insert(header_name.as_str(), value);
  }

  if let Some(build_id) = build_id {
    let mut metadata = remote_execution::RequestMetadata::default();
    metadata.tool_details = Some({
      let mut tool_details = remote_execution::ToolDetails::default();
      tool_details.tool_name = String::from("pants");
      tool_details
    });
    metadata.tool_invocation_id = build_id;
    // TODO: Maybe set action_id too
    let mut bytes = BytesMut::with_capacity(metadata.encoded_len());
    metadata
      .encode(&mut bytes)
      .map_err(|err| format!("Error serializing request metadata proto bytes: {}", err))?;
    let value = MetadataValue::from_bytes(bytes.as_ref());
    grpc_headers.insert_bin(
      "google.devtools.remoteexecution.v1test.requestmetadata-bin",
      value,
    );
  }

  Ok(grpc_headers)
}
