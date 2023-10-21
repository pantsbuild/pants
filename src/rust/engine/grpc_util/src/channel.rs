// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::task::{Context, Poll};

use http::{Request, Response, Uri};
use hyper::client::{HttpConnector, ResponseFuture};
use hyper_rustls::HttpsConnector;
use rustls::ClientConfig;
use tonic::body::BoxBody;
use tower_service::Service;

// Inspired by https://github.com/LucioFranco/tonic-openssl/blob/master/example/src/client2.rs.

/// Enumeration wrapping the HTTP and HTTPS clients so they can be treated equivalently by
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
}

impl Channel {
    pub async fn new(
        tls_config: Option<&ClientConfig>,
        uri: Uri,
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

        Ok(Self { client, uri })
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
        // Apparently the schema and authority do not get set by Hyper. Thus, the examples generally
        // opy the URI and replace the scheme and authority with the ones from the initial URI used
        // to configure the client.
        //
        // See https://github.com/LucioFranco/tonic-openssl/blob/bdaaecda437949244a1b4d61cb39110c4bcad019/example/src/client2.rs#L92
        // from the inspiration example
        let uri = Uri::builder()
            .scheme(self.uri.scheme().unwrap().clone())
            .authority(self.uri.authority().unwrap().clone())
            .path_and_query(req.uri().path_and_query().unwrap().clone())
            .build()
            .unwrap();
        *req.uri_mut() = uri;

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
    use http::{Request, Uri};
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

        let mut channel = Channel::new(None, uri).await.unwrap();

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

        let mut channel = Channel::new(Some(&tls_config), uri).await.unwrap();

        let request = Request::builder()
            .uri(format!("https://{}", addr))
            .body(tonic::body::empty_body())
            .unwrap();

        channel.ready().await.unwrap();
        let response = channel.call(request).await.unwrap();

        let body = hyper::body::to_bytes(response.into_body()).await.unwrap();
        assert_eq!(&body[..], TEST_RESPONSE);
    }

    #[tokio::test]
    async fn tls_mtls_client_request_test() {
        pub struct CertVerifierMock {
            saw_a_cert: std::sync::atomic::AtomicUsize,
        }

        impl rustls::server::ClientCertVerifier for CertVerifierMock {
            fn offer_client_auth(&self) -> bool {
                true
            }

            fn client_auth_root_subjects(&self) -> &[rustls::DistinguishedName] {
                &[]
            }

            fn verify_client_cert(
                &self,
                _end_entity: &rustls::Certificate,
                _intermediates: &[rustls::Certificate],
                _now: std::time::SystemTime,
            ) -> Result<rustls::server::ClientCertVerified, rustls::Error> {
                self.saw_a_cert
                    .fetch_add(1, std::sync::atomic::Ordering::SeqCst);

                Ok(rustls::server::ClientCertVerified::assertion())
            }
        }

        let cert_pem = std::fs::read(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("test-certs")
                .join("cert.pem"),
        )
        .unwrap();

        let key_pem = std::fs::read(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("test-certs")
                .join("key.pem"),
        )
        .unwrap();

        let certificates = rustls_pemfile::certs(&mut std::io::Cursor::new(&cert_pem))
            .unwrap()
            .into_iter()
            .map(rustls::Certificate)
            .collect::<Vec<_>>();

        let privkey = rustls::PrivateKey(
            rustls_pemfile::pkcs8_private_keys(&mut std::io::Cursor::new(&key_pem))
                .unwrap()
                .remove(0),
        );

        let mut root_store = rustls::RootCertStore::empty();
        root_store.add(&certificates[0]).unwrap();

        let verifier = Arc::new(CertVerifierMock {
            saw_a_cert: std::sync::atomic::AtomicUsize::new(0),
        });
        let mut config = rustls::ServerConfig::builder()
            .with_safe_defaults()
            .with_client_cert_verifier(verifier.clone())
            .with_single_cert(certificates.clone(), privkey.clone())
            .unwrap();

        config.alpn_protocols = vec![b"h2".to_vec(), b"http/1.1".to_vec()];

        let config = RustlsConfig::from_config(Arc::new(config));

        let bind_addr = "127.0.0.1:0".parse::<SocketAddr>().unwrap();
        let listener = std::net::TcpListener::bind(bind_addr).unwrap();
        let addr = listener.local_addr().unwrap();

        let server = axum_server::from_tcp_rustls(listener, config);

        tokio::spawn(async move {
            server.serve(router().into_make_service()).await.unwrap();
        });

        let uri = Uri::try_from(format!("https://{}", addr.to_string())).unwrap();

        let mut tls_config =
            crate::tls::Config::new(Some(&cert_pem), Some((&cert_pem, &key_pem))).unwrap();

        tls_config.certificate_check = crate::tls::CertificateCheck::DangerouslyDisabled;

        let tls_config: rustls::ClientConfig = tls_config.try_into().unwrap();

        let mut channel = Channel::new(Some(&tls_config), uri).await.unwrap();

        match &channel.client {
            super::Client::Plain(_) => panic!("Expected a TLS client"),
            super::Client::Tls(_) => {}
        }
        assert_eq!(
            verifier
                .saw_a_cert
                .load(std::sync::atomic::Ordering::SeqCst),
            0
        );
        let request = Request::builder()
            .uri(format!("https://{}", addr))
            .body(tonic::body::empty_body())
            .unwrap();

        channel.ready().await.unwrap();
        let response = channel.call(request).await.unwrap();

        let body = hyper::body::to_bytes(response.into_body()).await.unwrap();
        assert_eq!(&body[..], TEST_RESPONSE);

        assert_eq!(
            verifier
                .saw_a_cert
                .load(std::sync::atomic::Ordering::SeqCst),
            1
        );
    }
}
