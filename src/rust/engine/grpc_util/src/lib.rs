use std::convert::TryFrom;

use tokio_rustls::rustls::ClientConfig;
use tonic::transport::{Channel, ClientTlsConfig, Endpoint};

/// Create a Tonic `Endpoint` from a string containing a schema and IP address/name.
pub fn create_endpoint(
  addr: &str,
  tls_config_opt: Option<&ClientConfig>,
) -> Result<Endpoint, String> {
  let uri =
    tonic::transport::Uri::try_from(addr).map_err(|err| format!("invalid address: {}", err))?;
  let endpoint = Channel::builder(uri);
  let maybe_tls_endpoint = if let Some(tls_config) = tls_config_opt {
    endpoint
      .tls_config(ClientTlsConfig::new().rustls_client_config(tls_config.clone()))
      .map_err(|e| format!("TLS setup error: {}", e))?
  } else {
    endpoint
  };
  Ok(maybe_tls_endpoint)
}

/// Create a rust-tls `ClientConfig` from root CA certs.
pub fn create_tls_config(pem_bytes: Vec<u8>) -> Result<ClientConfig, String> {
  let mut tls_config = ClientConfig::new();

  // Must set HTTP/2 as ALPN protocol otherwise cannot connect over TLS to gRPC servers.
  // Unfortunately, this is not a default value and, moreover, Tonic does not provide
  // any helper function to encapsulate this knowledge.
  tls_config.set_protocols(&[Vec::from(&"h2"[..])]);

  let mut reader = std::io::Cursor::new(pem_bytes);
  tls_config
    .root_store
    .add_pem_file(&mut reader)
    .map_err(|_| "unexpected state in PEM file add".to_owned())?;

  Ok(tls_config)
}
