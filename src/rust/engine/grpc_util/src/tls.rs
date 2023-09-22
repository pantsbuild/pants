// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::sync::Arc;
use std::time::SystemTime;

use rustls::client::{ServerCertVerified, ServerCertVerifier};
use tokio_rustls::rustls::{Certificate, ClientConfig, Error, RootCertStore, ServerName};

#[derive(Default, Clone)]
pub struct Config {
  pub root_ca_certs: Option<Vec<Certificate>>,
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
      .map(|certs| {
        let raw_certs = rustls_pemfile::certs(&mut std::io::Cursor::new(certs.as_ref()))
          .map_err(|e| format!("Failed to read mTLS certs file: {e:?}"))?;
        Result::<_, String>::Ok(raw_certs.into_iter().map(rustls::Certificate).collect())
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
    let tls_config = ClientConfig::builder().with_safe_defaults();

    // Add the root certificate store.
    let tls_config = match config.certificate_check {
      CertificateCheck::DangerouslyDisabled => {
        let tls_config = tls_config.with_custom_certificate_verifier(Arc::new(NoVerifier));
        if let Some(MtlsConfig { cert_chain, key }) = config.mtls {
          tls_config
            .with_client_auth_cert(cert_chain, key)
            .map_err(|err| format!("Error creating mTLS config: {:?}", err))?
        } else {
          tls_config.with_no_client_auth()
        }
      }
      CertificateCheck::Enabled => {
        let tls_config = {
          let mut root_cert_store = RootCertStore::empty();

          match config.root_ca_certs {
            Some(certs) => {
              for cert in &certs {
                root_cert_store
                  .add(cert)
                  .map_err(|e| format!("failed adding CA cert to store: {e:?}"))?;
              }
            }
            None => {
              let native_root_certs = rustls_native_certs::load_native_certs().map_err(|err| {
                format!(
                "Could not discover root CA cert files to use TLS with remote caching and remote \
            execution. Consider setting `--remote-ca-certs-path` instead to explicitly point to \
            the correct PEM file.\n\n{err}",
              )
              })?;

              for cert in native_root_certs {
                root_cert_store.add_parsable_certificates(&[cert.0]);
              }
            }
          }

          tls_config.with_root_certificates(root_cert_store)
        };

        if let Some(MtlsConfig { cert_chain, key }) = config.mtls {
          tls_config
            .with_client_auth_cert(cert_chain, key)
            .map_err(|err| format!("Error creating mTLS config: {:?}", err))?
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
  /// DER bytes of the private key used for mTLS.
  pub key: rustls::PrivateKey,
  /// DER bytes of the certificate used for mTLS.
  pub cert_chain: Vec<rustls::Certificate>,
}

impl MtlsConfig {
  pub fn from_pem_buffers(certs: &[u8], key: &[u8]) -> Result<Self, String> {
    let cert_chain = rustls_pemfile::certs(&mut std::io::Cursor::new(certs))
      .map_err(|e| format!("Failed to read mTLS certs file: {e:?}"))?
      .into_iter()
      .map(rustls::Certificate)
      .collect();

    let keys = rustls_pemfile::read_all(&mut std::io::Cursor::new(key))
      .map_err(|e| format!("Failed to read mTLS key file: {e:?}"))?
      .into_iter()
      .filter(|item| match item {
        rustls_pemfile::Item::X509Certificate(_) => {
          log::warn!("Found x509 certificate in mTLS key file. Ignoring.");
          false
        }
        _ => true,
      });

    let mut key = None;
    for item in keys {
      use rustls_pemfile::Item;

      match item {
        Item::RSAKey(buf) | Item::PKCS8Key(buf) | Item::ECKey(buf) => {
          key = Some(rustls::PrivateKey(buf))
        }
        Item::X509Certificate(_) => unreachable!("filtered above"),
        _ => todo!("non-exhaustive match"),
      }
    }

    let key = key.ok_or_else(|| "No private key found in mTLS key file".to_owned())?;

    Ok(Self { key, cert_chain })
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

#[cfg(test)]
mod test {
  use super::Config;
  use std::path::PathBuf;

  #[test]
  fn test_client_auth_cert_resolver_is_unconfigured_no_mtls() {
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
