// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
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
  // TODO: Falsely triggers for async/await:
  //   see https://github.com/rust-lang/rust-clippy/issues/5360
  // clippy::used_underscore_binding
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

use std::convert::TryFrom;

use tokio_rustls::rustls::ClientConfig;
use tonic::transport::{Channel, ClientTlsConfig, Endpoint};

pub mod prost;

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
