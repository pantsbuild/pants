// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::sync::Arc;

use rustls::{ClientConfig, RootCertStore, ServerCertVerified, ServerCertVerifier, TLSError};
use webpki::DNSNameRef;

#[derive(Default)]
pub struct Config {
    pub root_ca_certs: Option<Vec<u8>>,
    pub mtls: Option<MtlsConfig>,
    pub certificate_check: CertificateCheck,
}

impl Config {
    pub fn new_without_mtls(root_ca_certs: Option<Vec<u8>>) -> Self {
        Self {
            root_ca_certs,
            mtls: None,
            certificate_check: CertificateCheck::Enabled,
        }
    }
}

impl TryFrom<Config> for ClientConfig {
    type Error = String;

    /// Create a rust-tls `ClientConfig` from root CA certs, falling back to the rust-tls-native-certs
    /// crate if specific root CA certs were not given.
    fn try_from(config: Config) -> Result<Self, Self::Error> {
        let mut tls_config = ClientConfig::new();

        // Must set HTTP/2 as ALPN protocol otherwise cannot connect over TLS to gRPC servers.
        // Unfortunately, this is not a default value and, moreover, Tonic does not provide
        // any helper function to encapsulate this knowledge.
        tls_config.set_protocols(&[Vec::from("h2")]);

        // Add the root store.
        match config.root_ca_certs {
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
            the correct PEM file.\n\n{e}"
            )
                    })?;
            }
        }

        if let Some(MtlsConfig { key, cert_chain }) = config.mtls {
            tls_config
                .set_single_client_cert(
                    cert_chain_from_pem_bytes(cert_chain)?,
                    der_key_from_pem_bytes(key)?,
                )
                .map_err(|err| format!("Error creating MTLS config: {err:?}"))?;
        }

        if let CertificateCheck::DangerouslyDisabled = config.certificate_check {
            tls_config
                .dangerous()
                .set_certificate_verifier(Arc::new(NoVerifier));
        }

        Ok(tls_config)
    }
}

pub struct MtlsConfig {
    /// PEM bytes of the private key used for MTLS.
    pub key: Vec<u8>,
    /// PEM bytes of the certificate used for MTLS.
    pub cert_chain: Vec<u8>,
}

pub enum CertificateCheck {
    Enabled,
    DangerouslyDisabled,
}

impl Default for CertificateCheck {
    fn default() -> Self {
        Self::Enabled
    }
}

struct NoVerifier;

impl ServerCertVerifier for NoVerifier {
    fn verify_server_cert(
        &self,
        _roots: &RootCertStore,
        _presented_certs: &[rustls::Certificate],
        _dns_name: DNSNameRef,
        _ocsp_response: &[u8],
    ) -> Result<ServerCertVerified, TLSError> {
        Ok(ServerCertVerified::assertion())
    }
}

fn cert_chain_from_pem_bytes(cert_chain: Vec<u8>) -> Result<Vec<rustls::Certificate>, String> {
    rustls_pemfile::certs(&mut cert_chain.as_slice())
        .and_then(|certs| {
            certs
                .into_iter()
                .map(|cert| Ok(rustls::Certificate(cert)))
                .collect::<Result<Vec<_>, _>>()
        })
        .map_err(|err| format!("Failed to parse certificates from PEM file {err:?}"))
}

fn der_key_from_pem_bytes(pem_bytes: Vec<u8>) -> Result<rustls::PrivateKey, String> {
    let key = rustls_pemfile::read_one(&mut pem_bytes.as_slice())
        .map_err(|err| format!("Failed to read PEM file: {err:?}"))?
        .ok_or_else(|| "No private key found in PEM file".to_owned())?;
    use rustls_pemfile::Item;
    let key = match key {
        Item::RSAKey(bytes) => bytes,
        Item::PKCS8Key(bytes) => bytes,
        Item::X509Certificate(_) => {
            return Err("Found certificate in PEM file but expected private key".to_owned())
        }
    };
    Ok(rustls::PrivateKey(key))
}
