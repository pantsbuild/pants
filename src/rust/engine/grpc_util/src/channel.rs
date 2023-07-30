// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::task::{Context, Poll};

use http::{HeaderMap, Request, Response, Uri};
use hyper::client::{HttpConnector, ResponseFuture};
use hyper_rustls::HttpsConnector;
use rustls::ClientConfig;
use tonic::body::BoxBody;
use tower_service::Service;

// Inspired by https://github.com/LucioFranco/tonic-openssl/blob/master/example/src/client2.rs.

/// Enumeration wrapping the HTTP and HTTPS clients so they can be treated equiavlent by
/// `Channel`.
#[derive(Clone, Debug)]
pub enum Client {
  Plain(hyper::Client<HttpConnector, BoxBody>),
  Tls(hyper::Client<HttpsConnector<HttpConnector>, BoxBody>),
}

/// A communication channel which may either communicate using HTTP or HTTP over TLS. This
/// `Channel` can be passed directly to Tonic clients as a connector.
///
/// `Channel` implements the `Service` expected by Tonic for the underlying communication channel.
/// This strategy is necessary because Tonic removed the ability to pass in a raw `rustls`
/// configuration, and so Pants must implement its own connection setup logic to be able to
/// continue to use `rustls` directly.
#[derive(Clone, Debug)]
pub struct Channel {
  client: Client,
  uri: Uri,
  headers: HeaderMap,
}

impl Channel {
  pub async fn new(
    tls_config: Option<&ClientConfig>,
    uri: Uri,
    headers: HeaderMap,
  ) -> Result<Self, Box<dyn std::error::Error>> {
    let client = match tls_config {
      None => {
        let mut http = HttpConnector::new();
        http.enforce_http(false);

        Client::Plain(hyper::Client::builder().http2_only(true).build(http))
      }
      Some(tls_config) => {
        let tls_config = tls_config.to_owned();

        let https = hyper_rustls::HttpsConnectorBuilder::new()
          .with_tls_config(tls_config)
          .https_or_http()
          .enable_http2()
          .build();

        Client::Tls(hyper::Client::builder().http2_only(true).build(https))
      }
    };

    Ok(Self {
      client,
      uri,
      headers,
    })
  }
}

impl Service<Request<BoxBody>> for Channel {
  type Response = Response<hyper::Body>;
  type Error = hyper::Error;
  type Future = ResponseFuture;

  fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
    Ok(()).into()
  }

  fn call(&mut self, mut req: Request<BoxBody>) -> Self::Future {
    let uri = Uri::builder()
      .scheme(self.uri.scheme().unwrap().clone())
      .authority(self.uri.authority().unwrap().clone())
      .path_and_query(req.uri().path_and_query().unwrap().clone())
      .build()
      .unwrap();
    *req.uri_mut() = uri;

    for (key, value) in &self.headers {
      req.headers_mut().insert(key, value.clone());
    }

    match &self.client {
      Client::Plain(client) => client.request(req),
      Client::Tls(client) => client.request(req),
    }
  }
}

#[cfg(test)]
mod tests {
  use std::net::SocketAddr;
  use std::path::PathBuf;
  use std::sync::Arc;

  use axum::{routing::get, Router};
  use axum_server::tls_rustls::RustlsConfig;
  use http::{HeaderMap, Request, Uri};
  use rustls::ClientConfig;
  use tower::ServiceExt;
  use tower_service::Service;

  use super::Channel;
  use crate::tls::NoVerifier;

  const TEST_RESPONSE: &[u8] = b"xyzzy";

  fn router() -> Router {
    Router::new().route("/", get(|| async { TEST_RESPONSE }))
  }

  #[tokio::test]
  async fn plain_client_request_test() {
    let bind_addr = "127.0.0.1:0".parse::<SocketAddr>().unwrap();
    let listener = std::net::TcpListener::bind(bind_addr).unwrap();
    let addr = listener.local_addr().unwrap();

    tokio::spawn(async move {
      axum::Server::from_tcp(listener)
        .unwrap()
        .serve(router().into_make_service())
        .await
        .unwrap();
    });

    let uri = Uri::try_from(format!("http://{}", addr.to_string())).unwrap();

    let mut channel = Channel::new(None, uri, HeaderMap::new()).await.unwrap();

    let request = Request::builder()
      .uri(format!("http://{}", addr))
      .body(tonic::body::empty_body())
      .unwrap();

    channel.ready().await.unwrap();
    let response = channel.call(request).await.unwrap();

    let body = hyper::body::to_bytes(response.into_body()).await.unwrap();
    assert_eq!(&body[..], TEST_RESPONSE);
  }

  #[tokio::test]
  async fn tls_client_request_test() {
    let config = RustlsConfig::from_pem_file(
      PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("test-certs")
        .join("cert.pem"),
      PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("test-certs")
        .join("key.pem"),
    )
    .await
    .unwrap();

    let bind_addr = "127.0.0.1:0".parse::<SocketAddr>().unwrap();
    let listener = std::net::TcpListener::bind(bind_addr).unwrap();
    let addr = listener.local_addr().unwrap();

    let server = axum_server::from_tcp_rustls(listener, config);

    tokio::spawn(async move {
      server.serve(router().into_make_service()).await.unwrap();
    });

    let uri = Uri::try_from(format!("https://{}", addr.to_string())).unwrap();

    let tls_config = ClientConfig::builder()
      .with_safe_defaults()
      .with_custom_certificate_verifier(Arc::new(NoVerifier))
      .with_no_client_auth();

    let mut channel = Channel::new(Some(&tls_config), uri, HeaderMap::new())
      .await
      .unwrap();

    let request = Request::builder()
      .uri(format!("https://{}", addr))
      .body(tonic::body::empty_body())
      .unwrap();

    channel.ready().await.unwrap();
    let response = channel.call(request).await.unwrap();

    let body = hyper::body::to_bytes(response.into_body()).await.unwrap();
    assert_eq!(&body[..], TEST_RESPONSE);
  }
}
