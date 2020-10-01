use std::collections::BTreeMap;
use std::sync::Arc;

use cpython::{ObjectProtocol, PyObject, Python};
use parking_lot::Mutex;
use protobuf::Message;

#[derive(Clone)]
pub enum RequestHeaders {
  None,
  Static {
    headers: BTreeMap<String, String>,
  },
  Dynamic {
    // Must be a Python callable which will receive the name of the gRPC service
    // being called and a mutable Dict[str, str] for the headers.
    callback: Arc<Mutex<PyObject>>,
  },
}

impl std::fmt::Debug for RequestHeaders {
  fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
    match self {
      RequestHeaders::None => f.write_str("RequestHeaders::None"),
      RequestHeaders::Static { headers } => headers.fmt(f),
      RequestHeaders::Dynamic { .. } => f.write_str("RequestHeaders::Dynamic(callback)"),
    }
  }
}

pub fn call_option(
  headers_provider: &RequestHeaders,
  build_id: Option<String>,
) -> Result<grpcio::CallOption, String> {
  // Convert a `RequestHeaders` headers into a specific list of headers to send.
  const OTHER_METADATA_ENTRIES: usize = 1;
  let mut builder = match headers_provider {
    RequestHeaders::None => grpcio::MetadataBuilder::with_capacity(OTHER_METADATA_ENTRIES),
    RequestHeaders::Static { headers } => {
      let mut builder =
        grpcio::MetadataBuilder::with_capacity(headers.len() + OTHER_METADATA_ENTRIES);
      for (header_name, header_value) in headers {
        builder
          .add_str(header_name.as_str(), header_value.as_str())
          .map_err(|err| format!("Error setting header {}: {}", header_name, err))?;
      }
      builder
    }
    RequestHeaders::Dynamic { callback } => {
      let headers_callable = callback.lock();
      let headers = {
        let gil = Python::acquire_gil();
        let result = headers_callable
          .call(gil.python(), (build_id.clone(),), None)
          .map_err(|err| format!("Error getting headers from Python: {:?}", err))?;
        result
          .extract::<Vec<(String, String)>>(gil.python())
          .map_err(|err| format!("Error getting headers from Python: {:?}", err))?
      };

      let mut builder =
        grpcio::MetadataBuilder::with_capacity(headers.len() + OTHER_METADATA_ENTRIES);
      for (header_name, header_value) in headers {
        builder
          .add_str(&header_name, &header_value)
          .map_err(|err| format!("Error setting header {}: {}", header_name, err))?;
      }
      builder
    }
  };

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
