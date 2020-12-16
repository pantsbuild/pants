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
