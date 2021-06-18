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

use std::collections::btree_map::Entry;
use std::collections::BTreeMap;
use std::convert::TryFrom;
use std::str::FromStr;

use http::header::USER_AGENT;
use tokio_rustls::rustls::ClientConfig;
use tonic::metadata::{AsciiMetadataKey, AsciiMetadataValue, KeyAndValueRef, MetadataMap};
use tonic::transport::{Channel, ClientTlsConfig, Endpoint};
use tower::limit::ConcurrencyLimit;
use tower::ServiceBuilder;

pub mod hyper;
pub mod prost;
pub mod retry;

// NB: Rather than boxing our tower/tonic services, we define a type alias that fully defines the
// Service layers that we use universally. If this type becomes unwieldy, or our various Services
// diverge in which layers they use, we should instead use a Box<dyn Service<..>>.
pub type LayeredService = ConcurrencyLimit<Channel>;

pub fn layered_service(channel: Channel) -> LayeredService {
  ServiceBuilder::new()
    // TODO
    .concurrency_limit(100)
    .service(channel)
}

/// Create a Tonic `Endpoint` from a string containing a schema and IP address/name.
pub fn create_endpoint(
  addr: &str,
  tls_config_opt: Option<&ClientConfig>,
  headers: &mut BTreeMap<String, String>,
) -> Result<Endpoint, String> {
  let uri =
    tonic::transport::Uri::try_from(addr).map_err(|err| format!("invalid address: {}", err))?;
  let endpoint = Channel::builder(uri);

  let endpoint = if let Some(tls_config) = tls_config_opt {
    endpoint
      .tls_config(ClientTlsConfig::new().rustls_client_config(tls_config.clone()))
      .map_err(|e| format!("TLS setup error: {}", e))?
  } else {
    endpoint
  };

  let endpoint = match headers.entry(USER_AGENT.as_str().to_owned()) {
    Entry::Occupied(e) => {
      let (_, user_agent) = e.remove_entry();
      endpoint
        .user_agent(user_agent)
        .map_err(|e| format!("Unable to convert user-agent header: {}", e))?
    }
    Entry::Vacant(_) => endpoint,
  };

  Ok(endpoint)
}

/// Create a rust-tls `ClientConfig` from root CA certs, falling back to the rust-tls-native-certs
/// crate if specific root CA certs were not given.
pub fn create_tls_config(root_ca_certs: Option<Vec<u8>>) -> Result<ClientConfig, String> {
  let mut tls_config = ClientConfig::new();

  // Must set HTTP/2 as ALPN protocol otherwise cannot connect over TLS to gRPC servers.
  // Unfortunately, this is not a default value and, moreover, Tonic does not provide
  // any helper function to encapsulate this knowledge.
  tls_config.set_protocols(&[Vec::from("h2")]);

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

#[cfg(test)]
mod tests {
  mod gen {
    tonic::include_proto!("test");
  }

  use std::collections::BTreeMap;

  use async_trait::async_trait;
  use futures::FutureExt;
  use tokio::sync::oneshot;
  use tonic::transport::{Channel, Server};
  use tonic::{Request, Response, Status};

  use crate::hyper::AddrIncomingWithStream;

  #[tokio::test]
  async fn user_agent_is_set_correctly() {
    const EXPECTED_USER_AGENT: &str = "testclient/0.0.1";

    #[derive(Clone)]
    struct UserAgentResponder;

    #[async_trait]
    impl gen::test_server::Test for UserAgentResponder {
      async fn call(&self, request: Request<gen::Input>) -> Result<Response<gen::Output>, Status> {
        match request.metadata().get("user-agent") {
          Some(user_agent_value) => {
            let user_agent = user_agent_value.to_str().map_err(|err| {
              Status::invalid_argument(format!(
                "Unable to convert user-agent header to string: {}",
                err
              ))
            })?;
            if user_agent.contains(EXPECTED_USER_AGENT) {
              Ok(Response::new(gen::Output {}))
            } else {
              Err(Status::invalid_argument(format!(
                "user-agent header did not contain expected value: actual={}",
                user_agent
              )))
            }
          }
          None => Err(Status::invalid_argument("user-agent header was not set")),
        }
      }
    }

    let addr = "127.0.0.1:0".parse().expect("failed to parse IP address");
    let incoming = hyper::server::conn::AddrIncoming::bind(&addr).expect("failed to bind port");
    let local_addr = incoming.local_addr();
    let incoming = AddrIncomingWithStream(incoming);

    // Setup shutdown signal handler.
    let (_shutdown_sender, shutdown_receiver) = oneshot::channel::<()>();

    tokio::spawn(async move {
      let mut server = Server::builder();
      let router = server.add_service(gen::test_server::TestServer::new(UserAgentResponder));
      router
        .serve_with_incoming_shutdown(incoming, shutdown_receiver.map(drop))
        .await
        .unwrap();
    });

    let mut headers = {
      let mut h = BTreeMap::new();
      h.insert("user-agent".to_owned(), EXPECTED_USER_AGENT.to_owned());
      h
    };

    let endpoint = super::create_endpoint(
      &format!("grpc://127.0.0.1:{}", local_addr.port()),
      None,
      &mut headers,
    )
    .unwrap();

    let channel = Channel::balance_list(vec![endpoint].into_iter());

    let mut client = gen::test_client::TestClient::new(channel);
    if let Err(err) = client.call(gen::Input {}).await {
      panic!("test failed: {}", err.message());
    }
  }
}
