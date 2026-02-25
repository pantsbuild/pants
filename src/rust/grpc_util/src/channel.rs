// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::pin::Pin;
use std::task::{Context, Poll};

use http::Uri;
use hyper::body::Incoming;
use hyper_rustls::HttpsConnector;
use hyper_util::client::legacy::{
    Client as HyperClient, Error as HyperClientError, connect::HttpConnector,
};
use hyper_util::rt::TokioExecutor;
use rustls::ClientConfig;
use tonic::body::BoxBody;
use tower_service::Service;

// Inspired by https://github.com/LucioFranco/tonic-openssl/blob/master/example/src/client2.rs.

/// Enumeration wrapping the HTTP and HTTPS clients so they can be treated equivalently by
/// `Channel`.
#[derive(Clone, Debug)]
pub enum Client {
    Plain(HyperClient<HttpConnector, BoxBody>),
    Tls(HyperClient<HttpsConnector<HttpConnector>, BoxBody>),
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
        crate::initialize()?;

        let mut http = HttpConnector::new();
        http.enforce_http(false);

        let client = match tls_config {
            None => Client::Plain(
                HyperClient::builder(TokioExecutor::new())
                    .http2_only(true)
                    .build(http),
            ),
            Some(tls_config) => {
                let tls_config = tls_config.to_owned();

                let https = hyper_rustls::HttpsConnectorBuilder::new()
                    .with_tls_config(tls_config)
                    .https_or_http()
                    .enable_http2()
                    .build();

                Client::Tls(
                    HyperClient::builder(TokioExecutor::new())
                        .http2_only(true)
                        .build(https),
                )
            }
        };

        Ok(Self { client, uri })
    }
}

impl Service<http::Request<BoxBody>> for Channel {
    type Response = http::Response<Incoming>;
    type Error = HyperClientError;
    type Future =
        Pin<Box<dyn std::future::Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, _: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, mut req: http::Request<BoxBody>) -> Self::Future {
        // Apparently the schema and authority do not get set by Hyper. Thus, the examples generally
        // copy the URI and replace the scheme and authority with the ones from the initial URI used
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

        let client = self.client.clone();
        Box::pin(async move {
            match &client {
                Client::Plain(client) => client.request(req).await,
                Client::Tls(client) => client.request(req).await,
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use std::net::SocketAddr;
    use std::path::PathBuf;
    use std::sync::Arc;

    use axum::{Router, routing::get};
    use axum_server::tls_rustls::RustlsConfig;
    use http::{Request, Uri};
    use http_body_util::BodyExt;
    use rustls::{
        ClientConfig, DigitallySignedStruct, RootCertStore, SignatureScheme,
        client::danger::HandshakeSignatureValid,
        crypto::{verify_tls12_signature, verify_tls13_signature},
    };
    use rustls_pki_types::{CertificateDer, UnixTime};
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
        listener.set_nonblocking(true).unwrap();
        let addr = listener.local_addr().unwrap();

        tokio::spawn(async move {
            axum_server::from_tcp(listener)
                .expect("Unable to create Server from std::net::TcpListener")
                .serve(router().into_make_service())
                .await
                .unwrap();
        });

        let uri = Uri::try_from(format!("http://{addr}")).unwrap();

        let mut channel = Channel::new(None, uri).await.unwrap();

        let request = Request::builder()
            .uri(format!("http://{addr}"))
            .body(tonic::body::empty_body())
            .unwrap();

        channel.ready().await.unwrap();
        let response = channel.call(request).await.unwrap();

        let body = response.collect().await.unwrap();
        assert_eq!(body.to_bytes().as_ref(), TEST_RESPONSE);
    }

    #[tokio::test]
    async fn tls_client_request_test() {
        crate::initialize().expect("init crate");

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
        listener.set_nonblocking(true).unwrap();
        let addr = listener.local_addr().unwrap();

        let server = axum_server::from_tcp_rustls(listener, config)
            .expect("Unable to create Server from std::net::TcpListener");

        tokio::spawn(async move {
            server.serve(router().into_make_service()).await.unwrap();
        });

        let uri = Uri::try_from(format!("https://{addr}")).unwrap();

        let mut tls_config = ClientConfig::builder()
            .with_root_certificates(RootCertStore::empty())
            .with_no_client_auth();

        tls_config
            .dangerous()
            .set_certificate_verifier(Arc::new(NoVerifier));

        let mut channel = Channel::new(Some(&tls_config), uri).await.unwrap();

        let request = Request::builder()
            .uri(format!("https://{addr}"))
            .body(tonic::body::empty_body())
            .unwrap();

        channel.ready().await.unwrap();
        let response = channel.call(request).await.unwrap();

        let body = response.collect().await.unwrap();
        assert_eq!(body.to_bytes().as_ref(), TEST_RESPONSE);
    }

    #[tokio::test]
    async fn tls_mtls_client_request_test() {
        crate::initialize().expect("init crate");

        #[derive(Debug)]
        pub struct CertVerifierMock {
            saw_a_cert: std::sync::atomic::AtomicUsize,
        }

        impl rustls::server::danger::ClientCertVerifier for CertVerifierMock {
            fn offer_client_auth(&self) -> bool {
                true
            }

            fn root_hint_subjects(&self) -> &[rustls::DistinguishedName] {
                &[]
            }

            fn verify_client_cert(
                &self,
                _end_entity: &CertificateDer<'_>,
                _intermediates: &[CertificateDer<'_>],
                _now: UnixTime,
            ) -> Result<rustls::server::danger::ClientCertVerified, rustls::Error> {
                self.saw_a_cert
                    .fetch_add(1, std::sync::atomic::Ordering::SeqCst);

                Ok(rustls::server::danger::ClientCertVerified::assertion())
            }

            fn verify_tls12_signature(
                &self,
                message: &[u8],
                cert: &CertificateDer<'_>,
                dss: &DigitallySignedStruct,
            ) -> Result<HandshakeSignatureValid, rustls::Error> {
                verify_tls12_signature(
                    message,
                    cert,
                    dss,
                    &rustls::crypto::aws_lc_rs::default_provider()
                        .signature_verification_algorithms,
                )
            }

            fn verify_tls13_signature(
                &self,
                message: &[u8],
                cert: &CertificateDer<'_>,
                dss: &DigitallySignedStruct,
            ) -> Result<HandshakeSignatureValid, rustls::Error> {
                verify_tls13_signature(
                    message,
                    cert,
                    dss,
                    &rustls::crypto::aws_lc_rs::default_provider()
                        .signature_verification_algorithms,
                )
            }

            fn supported_verify_schemes(&self) -> Vec<SignatureScheme> {
                rustls::crypto::aws_lc_rs::default_provider()
                    .signature_verification_algorithms
                    .supported_schemes()
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
            .collect::<Result<Vec<_>, _>>()
            .unwrap();

        let privkey = rustls_pemfile::private_key(&mut std::io::Cursor::new(&key_pem))
            .unwrap()
            .unwrap();

        let mut root_store = rustls::RootCertStore::empty();
        for cert in &certificates {
            root_store.add(cert.clone()).unwrap();
        }

        let verifier = Arc::new(CertVerifierMock {
            saw_a_cert: std::sync::atomic::AtomicUsize::new(0),
        });
        let mut config = rustls::ServerConfig::builder()
            .with_client_cert_verifier(verifier.clone())
            .with_single_cert(certificates.clone(), privkey)
            .unwrap();

        config.alpn_protocols = vec![b"h2".to_vec(), b"http/1.1".to_vec()];

        let config = RustlsConfig::from_config(Arc::new(config));

        let bind_addr = "127.0.0.1:0".parse::<SocketAddr>().unwrap();
        let listener = std::net::TcpListener::bind(bind_addr).unwrap();
        listener.set_nonblocking(true).unwrap();
        let addr = listener.local_addr().unwrap();

        let server = axum_server::from_tcp_rustls(listener, config)
            .expect("Unable to create Server from std::net::TcpListener");

        tokio::spawn(async move {
            server.serve(router().into_make_service()).await.unwrap();
        });

        let uri = Uri::try_from(format!("https://{addr}")).unwrap();

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
            .uri(format!("https://{addr}"))
            .body(tonic::body::empty_body())
            .unwrap();

        channel.ready().await.unwrap();
        let response = channel.call(request).await.unwrap();

        let body = response.collect().await.unwrap();
        assert_eq!(body.to_bytes().as_ref(), TEST_RESPONSE);

        assert_eq!(
            verifier
                .saw_a_cert
                .load(std::sync::atomic::Ordering::SeqCst),
            1
        );
    }
}
