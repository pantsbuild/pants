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

use std::collections::BTreeMap;
use std::convert::TryFrom;
use std::str::FromStr;

use tokio_rustls::rustls::ClientConfig;
use tonic::metadata::{AsciiMetadataKey, AsciiMetadataValue, KeyAndValueRef, MetadataMap};
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

/// Create a rust-tls `ClientConfig` from root CA certs, falling back to the rust-tls-native-certs
/// crate if specific root CA certs were not given.
pub fn create_tls_config(root_ca_certs: Option<Vec<u8>>) -> Result<ClientConfig, String> {
  let mut tls_config = ClientConfig::new();

  // Must set HTTP/2 as ALPN protocol otherwise cannot connect over TLS to gRPC servers.
  // Unfortunately, this is not a default value and, moreover, Tonic does not provide
  // any helper function to encapsulate this knowledge.
  tls_config.set_protocols(&[Vec::from(&"h2"[..])]);

  // Add the root store.
  match root_ca_certs {
    Some(pem_bytes) => {
      let mut reader = std::io::Cursor::new(pem_bytes);
      tls_config
        .root_store
        .add_pem_file(&mut reader)
        .map_err(|_| {
          "Unexpected state when adding PEM file from `--remote-ca-certs-path`. Please \
          check that it points to a valid file."
            .to_owned()
        })?;
    }
    None => {
      tls_config.root_store =
        rustls_native_certs::load_native_certs().map_err(|(_maybe_store, e)| {
          format!(
            "Could not discover root CA cert files to use TLS with remote caching and remote \
            execution. Consider setting `--remote-ca-certs-path` instead to explicitly point to \
            the correct PEM file.\n\n{}",
            e
          )
        })?;
    }
  }

  Ok(tls_config)
}

pub fn headers_to_metadata_map(headers: &BTreeMap<String, String>) -> Result<MetadataMap, String> {
  let mut metadata_map = MetadataMap::with_capacity(headers.len());
  for (key, value) in headers {
    let key_ascii = AsciiMetadataKey::from_str(key.as_str()).map_err(|_| {
      format!(
        "Header key `{}` must be an ASCII value (as required by gRPC).",
        key
      )
    })?;
    let value_ascii = AsciiMetadataValue::from_str(value.as_str()).map_err(|_| {
      format!(
        "Header value `{}` for key `{}` must be an ASCII value (as required by gRPC).",
        value, key
      )
    })?;
    metadata_map.insert(key_ascii, value_ascii);
  }
  Ok(metadata_map)
}

pub fn headers_to_interceptor_fn(
  headers: &BTreeMap<String, String>,
) -> Result<
  impl Fn(tonic::Request<()>) -> Result<tonic::Request<()>, tonic::Status> + Send + Sync + 'static,
  String,
> {
  let metadata_map = headers_to_metadata_map(headers)?;
  Ok(move |mut req: tonic::Request<()>| {
    let req_metadata = req.metadata_mut();
    for kv_ref in metadata_map.iter() {
      match kv_ref {
        KeyAndValueRef::Ascii(key, value) => {
          req_metadata.insert(key, value.clone());
        }
        KeyAndValueRef::Binary(key, value) => {
          req_metadata.insert_bin(key, value.clone());
        }
      }
    }
    Ok(req)
  })
}

pub fn status_to_str(status: tonic::Status) -> String {
  format!("{:?}: {:?}", status.code(), status.message())
}
