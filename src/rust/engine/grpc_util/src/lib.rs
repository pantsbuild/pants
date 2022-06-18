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
  clippy::used_underscore_binding
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
#![allow(unused_imports)]

use std::collections::{BTreeMap, HashMap};
use std::iter::FromIterator;
use std::pin::Pin;
use std::str::FromStr;
use std::sync::Arc;

use ::hyper::client::HttpConnector;
use ::hyper::Uri;
use either::Either;
use futures::future::BoxFuture;
use http::header::{HeaderName, USER_AGENT};
use http::{HeaderMap, HeaderValue};
use itertools::Itertools;
use lazy_static::lazy_static;
use tokio_rustls::rustls::ClientConfig;
use tonic::body::BoxBody;
use tonic::transport::Channel;
use tonic::Status;
use tower::limit::ConcurrencyLimit;
use tower::util::{BoxService, MapRequest};
use tower::ServiceBuilder;
use tower_service::Service;
use workunit_store::ObservationMetric;

use crate::headers::{SetRequestHeaders, SetRequestHeadersLayer};
use crate::metrics::{NetworkMetrics, NetworkMetricsLayer};
// use crate::boxed::BoxServiceSync;

// pub mod boxed;
pub mod headers;
pub mod hyper_util;
pub mod metrics;
pub mod prost;
pub mod retry;
pub mod tls;

// NB: Rather than boxing our tower/tonic services, we define a type alias that fully defines the
// Service layers that we use universally. If this type becomes unwieldy, or our various Services
// diverge in which layers they use, we should instead use a Box<dyn Service<..>>.
pub type LayeredService = Pin<Box<
  dyn Service<
      http::Request<BoxBody>,
      Response = hyper::Response<hyper::Body>,
      Error = hyper::Error,
      Future = BoxFuture<'static, Result<hyper::Response<hyper::Body>, hyper::Error>>,
    > + Send
    + Sync
    + 'static,
>>;

pub fn layered_service(
  service: LayeredService,
  concurrency_limit: usize,
  http_headers: HeaderMap,
) -> LayeredService {
  let service = ServiceBuilder::new()
    // .layer(BoxServiceSync::layer())
    .boxed()
    .layer(SetRequestHeadersLayer::new(http_headers))
    .concurrency_limit(concurrency_limit)
    .layer(NetworkMetricsLayer::new(&METRIC_FOR_REAPI_PATH))
    .service(service);

  Box::pin(service) as LayeredService
}

lazy_static! {
  static ref METRIC_FOR_REAPI_PATH: Arc<HashMap<String, ObservationMetric>> = {
    let mut m = HashMap::new();
    m.insert(
      "/build.bazel.remote.execution.v2.ActionCache/GetActionResult".to_string(),
      ObservationMetric::RemoteCacheGetActionResultNetworkTimeMicros,
    );
    Arc::new(m)
  };
}

/// Create a Hyper client for use by gRPC users.
///
/// This cannot use Tonic's wrappers because Tonic removed the ability to specify rustls client
/// config in its API in the latest version. Tonic's recommended way to use rustls now is to
/// manually setup the connection as per the example at:
/// https://github.com/hyperium/tonic/blob/master/examples/src/tls/client_rustls.rs
pub fn create_endpoint(
  addr: &str,
  tls_config: Option<&ClientConfig>,
  _headers: &mut BTreeMap<String, String>,
) -> Result<LayeredService, String> {
  let mut http = HttpConnector::new();
  http.enforce_http(false);

  let connector = if let Some(tls_config) = tls_config {
    hyper_rustls::HttpsConnectorBuilder::new()
      .with_tls_config(tls_config.clone())
      .https_or_http()
      .enable_http2()
      .build()
  } else {
    hyper_rustls::HttpsConnectorBuilder::new()
      .with_native_roots()
      .https_or_http()
      .enable_http2()
      .build()
  };

  let client: hyper::Client<_, tonic::body::BoxBody> = hyper::Client::builder().build(connector);

  // Hyper expects an absolute `Uri` to allow it to know which server to connect too.
  // Currently, tonic's generated code only sets the `path_and_query` section so we
  // are going to write a custom tower layer in front of the hyper client to add the
  // scheme and authority.
  let uri = Uri::from_str(addr).map_err(|_| format!("Invalid URL"))?;
  let svc = tower::ServiceBuilder::new()
    .boxed()
    .map_request(move |mut req: http::Request<tonic::body::BoxBody>| {
      let uri = Uri::builder()
        .scheme(uri.scheme().unwrap().clone())
        .authority(uri.authority().unwrap().clone())
        .path_and_query(req.uri().path_and_query().unwrap().clone())
        .build()
        .unwrap();
      *req.uri_mut() = uri;

      req
    })
    .service(client);

  Ok(Box::new(svc) as LayeredService)
}

pub fn headers_to_http_header_map(headers: &BTreeMap<String, String>) -> Result<HeaderMap, String> {
  let (http_headers, errors): (Vec<(HeaderName, HeaderValue)>, Vec<String>) = headers
    .iter()
    .map(|(key, value)| {
      let header_name =
        HeaderName::from_str(key).map_err(|err| format!("Invalid header name {}: {}", key, err))?;

      let header_value = HeaderValue::from_str(value)
        .map_err(|err| format!("Invalid header value {}: {}", value, err))?;

      Ok((header_name, header_value))
    })
    .partition_map(|result| match result {
      Ok(v) => Either::Left(v),
      Err(err) => Either::Right(err),
    });

  if !errors.is_empty() {
    return Err(format!("header conversion errors: {}", errors.join("; ")));
  }

  Ok(HeaderMap::from_iter(http_headers))
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

  use crate::hyper_util::AddrIncomingWithStream;

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
      &format!("http://127.0.0.1:{}", local_addr.port()),
      None,
      &mut headers,
    )
    .unwrap();

    let mut client = gen::test_client::TestClient::new(endpoint);
    client.call(gen::Input {}).await.expect("success");
  }
}
