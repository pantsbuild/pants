// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::fmt::Write;
use std::io;
use std::sync::Arc;

use rustls::{
    client::danger::{HandshakeSignatureValid, ServerCertVerified, ServerCertVerifier},
    crypto::{verify_tls12_signature, verify_tls13_signature},
    DigitallySignedStruct,
};
use rustls_pki_types::{CertificateDer, PrivateKeyDer, ServerName, UnixTime};
use tokio_rustls::rustls::{ClientConfig, RootCertStore};

#[derive(Default, Clone)]
pub struct Config {
    pub root_ca_certs: Option<Vec<CertificateDer<'static>>>,
    pub mtls: Option<MtlsConfig>,
    pub certificate_check: CertificateCheck,
}

impl Config {
    /// Creates a new config with the given root CA certs and mTLS config.
    pub fn new<Buf: AsRef<[u8]>>(
        root_ca_certs: Option<Buf>,
        mtls: Option<(Buf, Buf)>,
    ) -> Result<Self, String> {
        let root_ca_certs = root_ca_certs
            .map(|raw_certs| {
                let certs: Vec<CertificateDer<'static>> =
                    rustls_pemfile::certs(&mut std::io::Cursor::new(raw_certs.as_ref()))
                        .try_fold(vec![], |mut xs, result| {
                            xs.push(result?);
                            Ok(xs)
                        })
                        .map_err(|e: io::Error| format!("Failed to parse TLS certs data: {e:?}"))?;
                Result::<Vec<_>, String>::Ok(certs)
            })
            .transpose()?;

        let mtls = mtls
            .map(|buffers| MtlsConfig::from_pem_buffers(buffers.0.as_ref(), buffers.1.as_ref()))
            .transpose()?;

        Ok(Self {
            root_ca_certs,
            mtls,
            certificate_check: CertificateCheck::Enabled,
        })
    }
}

impl TryFrom<Config> for ClientConfig {
    type Error = String;

    /// Create a rust-tls `ClientConfig` from root CA certs, falling back to the rust-tls-native-certs
    /// crate if specific root CA certs were not given.
    fn try_from(config: Config) -> Result<Self, Self::Error> {
        // let tls_config = ClientConfig::builder().with_safe_defaults();
        let tls_config = ClientConfig::builder();

        // Add the root certificate store.
        let tls_config = match config.certificate_check {
            CertificateCheck::DangerouslyDisabled => {
                let tls_config = tls_config
                    .dangerous()
                    .with_custom_certificate_verifier(Arc::new(NoVerifier));
                if let Some(MtlsConfig { cert_chain, key }) = config.mtls {
                    let key = key.clone_key();
                    tls_config
                        .with_client_auth_cert(cert_chain, key)
                        .map_err(|err| {
                            format!("Error setting client authentication configuration: {err:?}")
                        })?
                } else {
                    tls_config.with_no_client_auth()
                }
            }
            CertificateCheck::Enabled => {
                let tls_config = {
                    let mut root_cert_store = RootCertStore::empty();

                    match config.root_ca_certs {
                        Some(certs) => {
                            for cert in certs.into_iter() {
                                root_cert_store.add(cert).map_err(|e| {
                                    format!("failed adding CA cert to store: {e:?}")
                                })?;
                            }
                        }
                        None => {
                            let native_root_certs_result = rustls_native_certs::load_native_certs();
                            if !native_root_certs_result.errors.is_empty() {
                                let mut msg = String::from("Could not discover root CA cert files to use TLS with remote caching and remote \
            execution. Consider setting `--remote-ca-certs-path` instead to explicitly point to \
            the correct PEM file. Error(s):\n\n");
                                for error in &native_root_certs_result.errors {
                                    write!(&mut msg, "{}\n\n", &error).expect("write into mutable string");
                                }
                                return Err(msg);
                            }

                            root_cert_store
                                .add_parsable_certificates(native_root_certs_result.certs);
                        }
                    }

                    tls_config.with_root_certificates(root_cert_store)
                };

                if let Some(MtlsConfig { cert_chain, key }) = config.mtls {
                    let key = key.clone_key();
                    tls_config
                        .with_client_auth_cert(cert_chain, key)
                        .map_err(|err| {
                            format!("Error setting client authentication configuration: {err:?}")
                        })?
                } else {
                    tls_config.with_no_client_auth()
                }
            }
        };

        Ok(tls_config)
    }
}

#[derive(Clone)]
pub struct MtlsConfig {
    /// DER bytes of the certificate used for mTLS.
    pub cert_chain: Vec<CertificateDer<'static>>,
    /// DER bytes of the private key used for mTLS.
    pub key: Arc<PrivateKeyDer<'static>>,
}

impl MtlsConfig {
    pub fn from_pem_buffers(certs: &[u8], key: &[u8]) -> Result<Self, String> {
        let cert_chain: Vec<CertificateDer<'static>> =
            rustls_pemfile::certs(&mut std::io::Cursor::new(certs))
                .try_fold(vec![], |mut certs, cert_result| {
                    certs.push(cert_result?);
                    Ok(certs)
                })
                .map_err(|e: std::io::Error| {
                    format!("Failed to parse client authentication (mTLS) certs data: {e:?}")
                })?;

        let key = rustls_pemfile::private_key(&mut std::io::Cursor::new(key))
            .map_err(|e| format!("Failed to parse client authentication (mTLS) key data: {e:?}"))?
            .ok_or_else(|| {
                "No private key found in client authentication (mTLS) key data".to_owned()
            })?;

        Ok(Self {
            cert_chain,
            key: Arc::new(key),
        })
    }
}

#[derive(Clone)]
pub enum CertificateCheck {
    Enabled,
    DangerouslyDisabled,
}

impl Default for CertificateCheck {
    fn default() -> Self {
        Self::Enabled
    }
}

#[derive(Debug)]
pub(crate) struct NoVerifier;

impl ServerCertVerifier for NoVerifier {
    fn verify_server_cert(
        &self,
        _end_entity: &CertificateDer<'_>,
        _intermediates: &[CertificateDer<'_>],
        _server_name: &ServerName<'_>,
        _ocsp: &[u8],
        _now: UnixTime,
    ) -> Result<ServerCertVerified, rustls::Error> {
        Ok(ServerCertVerified::assertion())
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
            &rustls::crypto::aws_lc_rs::default_provider().signature_verification_algorithms,
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
            &rustls::crypto::aws_lc_rs::default_provider().signature_verification_algorithms,
        )
    }

    fn supported_verify_schemes(&self) -> Vec<rustls::SignatureScheme> {
        rustls::crypto::aws_lc_rs::default_provider()
            .signature_verification_algorithms
            .supported_schemes()
    }
}

#[cfg(test)]
mod test {
    use super::Config;
    use std::path::PathBuf;

    #[test]
    fn test_client_auth_cert_resolver_is_unconfigured_no_mtls() {
        let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();

        let cert_pem = std::fs::read(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("test-certs")
                .join("cert.pem"),
        )
        .unwrap();

        let config = Config::new(Some(&cert_pem), None).unwrap();

        assert!(config.root_ca_certs.is_some());
        assert!(config.mtls.is_none());

        let rustls_config: rustls::ClientConfig = config.try_into().unwrap();

        assert!(!rustls_config.client_auth_cert_resolver.has_certs());
    }

    #[test]
    fn test_client_auth_cert_resolver_is_configured() {
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

        let config = Config::new(Some(&cert_pem), Some((&cert_pem, &key_pem))).unwrap();

        assert!(config.root_ca_certs.is_some());
        assert!(config.mtls.is_some());

        let rustls_config: rustls::ClientConfig = config.try_into().unwrap();

        assert!(rustls_config.client_auth_cert_resolver.has_certs());
    }
}
