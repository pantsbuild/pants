use protobuf::Message;
use std::collections::BTreeMap;

pub fn call_option(
  headers: &BTreeMap<String, String>,
  build_id: Option<String>,
) -> Result<grpcio::CallOption, String> {
  let mut builder = grpcio::MetadataBuilder::with_capacity(headers.len() + 1);
  for (header_name, header_value) in headers {
    builder
      .add_str(header_name, header_value)
      .map_err(|err| format!("Error setting header {}: {}", header_name, err))?;
  }
  if let Some(build_id) = build_id {
    let mut metadata = crate::remote_execution::RequestMetadata::new();
    metadata.set_tool_details({
      let mut tool_details = crate::remote_execution::ToolDetails::new();
      tool_details.set_tool_name(String::from("pants"));
      tool_details
    });
    metadata.set_tool_invocation_id(build_id);
    // TODO: Maybe set action_id too
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
