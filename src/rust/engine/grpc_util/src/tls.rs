// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::sync::Arc;
use std::time::SystemTime;

use rustls::client::{ServerCertVerified, ServerCertVerifier};
use tokio_rustls::rustls::{Certificate, ClientConfig, Error, RootCertStore, ServerName};

#[derive(Default, Clone)]
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
    // let tls_config = ClientConfig::builder().with_safe_defaults();
    let tls_config = ClientConfig::builder().with_safe_defaults();

    // Add the root certificate store.
    let mut tls_config = match config.certificate_check {
      CertificateCheck::DangerouslyDisabled => {
        let tls_config = tls_config.with_custom_certificate_verifier(Arc::new(NoVerifier));
        if let Some(MtlsConfig { key, cert_chain }) = config.mtls {
          tls_config
            .with_client_auth_cert(
              cert_chain_from_pem_bytes(cert_chain)?,
              der_key_from_pem_bytes(key)?,
            )
            .map_err(|err| format!("Error creating MTLS config: {:?}", err))?
        } else {
          tls_config.with_no_client_auth()
        }
      }
      CertificateCheck::Enabled => {
        let tls_config = match config.root_ca_certs {
          Some(pem_bytes) => {
            let reader = std::io::Cursor::new(pem_bytes);
            let mut reader = std::io::BufReader::new(reader);
            let certs = rustls_pemfile::certs(&mut reader)
              .map_err(|err| format!("Failed to read PEM certificate: {err}"))?;
            let mut root_cert_store = RootCertStore::empty();
            root_cert_store.add_parsable_certificates(&certs);
            tls_config.with_root_certificates(root_cert_store)
          }
          None => {
            let native_root_certs = rustls_native_certs::load_native_certs().map_err(|err| {
              format!(
                "Could not discover root CA cert files to use TLS with remote caching and remote \
            execution. Consider setting `--remote-ca-certs-path` instead to explicitly point to \
            the correct PEM file.\n\n{err}",
              )
            })?;
            let mut root_cert_store = RootCertStore::empty();
            for cert in native_root_certs {
              root_cert_store.add_parsable_certificates(&[cert.0]);
            }
            tls_config.with_root_certificates(root_cert_store)
          }
        };

        if let Some(MtlsConfig { key, cert_chain }) = config.mtls {
          tls_config
            .with_client_auth_cert(
              cert_chain_from_pem_bytes(cert_chain)?,
              der_key_from_pem_bytes(key)?,
            )
            .map_err(|err| format!("Error creating MTLS config: {:?}", err))?
        } else {
          tls_config.with_no_client_auth()
        }
      }
    };

    tls_config.alpn_protocols = vec![b"h2".to_vec()];
    Ok(tls_config)
  }
}

#[derive(Clone)]
pub struct MtlsConfig {
  /// PEM bytes of the private key used for MTLS.
  pub key: Vec<u8>,
  /// PEM bytes of the certificate used for MTLS.
  pub cert_chain: Vec<u8>,
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

pub(crate) struct NoVerifier;

impl ServerCertVerifier for NoVerifier {
  fn verify_server_cert(
    &self,
    _end_entity: &Certificate,
    _intermediates: &[Certificate],
    _server_name: &ServerName,
    _scts: &mut dyn Iterator<Item = &[u8]>,
    _ocsp_response: &[u8],
    _now: SystemTime,
  ) -> Result<ServerCertVerified, Error> {
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

fn der_key_from_pem_bytes(pem_bytes: Vec<u8>) -> Result<tokio_rustls::rustls::PrivateKey, String> {
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
    Item::ECKey(_) => {
      return Err("EC certificate not currently supported. Contact Pantsbuild Slack.".to_owned())
    }
    _ => return Err("Unknown entry in PEM file. Contact Pantsbuild Slack.".to_owned()),
  };
  Ok(rustls::PrivateKey(key))
}
