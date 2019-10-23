use protobuf::Message;
use std::collections::BTreeMap;

pub fn call_option(
  headers: &BTreeMap<String, String>,
  build_id: Option<String>,
  action_digest: Option<hashing::Digest>,
) -> Result<grpcio::CallOption, String> {
  let mut builder = grpcio::MetadataBuilder::with_capacity(headers.len() + 1);
  for (header_name, header_value) in headers {
    builder
      .add_str(header_name, header_value)
      .map_err(|err| format!("Error setting header {}: {}", header_name, err))?;
  }
  if build_id.is_some() || action_digest.is_some() {
    let mut metadata = crate::remote_execution::RequestMetadata::new();
    metadata.set_tool_details({
      let mut tool_details = crate::remote_execution::ToolDetails::new();
      tool_details.set_tool_name(String::from("pants"));
      tool_details
    });
    if let Some(build_id) = build_id {
      metadata.set_tool_invocation_id(build_id);
    }
    if let Some(action_digest) = action_digest {
      metadata.set_action_id(format!("{}-{}", action_digest.0, action_digest.1));
    }
    let bytes = metadata
      .write_to_bytes()
      .map_err(|err| format!("Error serializing request metadata proto bytes: {}", err))?;
    builder
      .add_bytes(
        "google.devtools.remoteexecution.v1test.requestmetadata-bin",
        &bytes,
      )
      .map_err(|err| format!("Error setting request metadata header: {}", err))?;
  }
  Ok(grpcio::CallOption::default().headers(builder.build()))
}
