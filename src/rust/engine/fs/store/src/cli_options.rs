// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::{collections::BTreeMap, path::PathBuf, time::Duration};

use clap::Parser;
use remote_provider::{RemoteProvider, RemoteStoreOptions};
use task_executor::Executor;

use crate::Store;

#[derive(Parser)]
pub struct StoreCliOpt {
    ///Path to lmdb directory used for local file storage.
    #[arg(long)]
    local_store_path: Option<PathBuf>,

    #[arg(long)]
    pub remote_instance_name: Option<String>,

    /// The host:port of the gRPC CAS server to connect to.
    #[arg(long)]
    pub cas_server: Option<String>,

    /// Path to file containing root certificate authority certificates for the CAS server.
    /// If not set, TLS will not be used when connecting to the CAS server.
    #[arg(long)]
    pub cas_root_ca_cert_file: Option<PathBuf>,

    /// Path to file containing client certificates for the CAS server.
    /// If not set, client authentication will not be used when connecting to the CAS server.
    #[arg(long)]
    pub cas_client_certs_file: Option<PathBuf>,

    /// Path to file containing client key for the CAS server.
    /// If not set, client authentication will not be used when connecting to the CAS server.
    #[arg(long)]
    pub cas_client_key_file: Option<PathBuf>,

    /// Path to file containing oauth bearer token for communication with the CAS server.
    /// If not set, no authorization will be provided to remote servers.
    #[arg(long)]
    pub cas_oauth_bearer_token_path: Option<PathBuf>,

    /// Number of bytes to include per-chunk when uploading bytes.
    /// grpc imposes a hard message-size limit of around 4MB.
    #[arg(long, default_value = "3145728")]
    pub upload_chunk_bytes: usize,

    /// Number of retries per request to the store service.
    #[arg(long, default_value = "3")]
    pub store_rpc_retries: usize,

    /// Number of concurrent requests to the store service.
    #[arg(long, default_value = "128")]
    pub store_rpc_concurrency: usize,

    /// Total size of blobs allowed to be sent in a single API call.
    #[arg(long, default_value = "4194304")]
    pub store_batch_api_size_limit: usize,

    /// Extra header to pass on remote execution request.
    #[arg(long)]
    pub header: Vec<String>,
}

impl StoreCliOpt {
    pub fn get_headers(
        &self,
        oauth_bearer_token_path: &Option<PathBuf>,
    ) -> Result<BTreeMap<String, String>, String> {
        let mut headers: BTreeMap<String, String> = collection_from_keyvalues(self.header.iter());
        if let Some(ref oauth_path) = oauth_bearer_token_path {
            let token = std::fs::read_to_string(oauth_path)
                .map_err(|e| format!("Error reading oauth bearer token file: {}", e))?;
            headers.insert(
                "authorization".to_owned(),
                format!("Bearer {}", token.trim()),
            );
        }
        Ok(headers)
    }

    pub async fn create_store(&self, executor: Executor) -> Result<Store, String> {
        let local_store_path = self
            .local_store_path
            .clone()
            .unwrap_or_else(Store::default_path);

        let local_only_store = Store::local_only(executor.clone(), local_store_path)?;

        if let Some(cas_server) = &self.cas_server {
            let tls_config = grpc_util::tls::Config::new_from_files(
                self.cas_root_ca_cert_file.as_deref(),
                self.cas_client_certs_file.as_deref(),
                self.cas_client_key_file.as_deref(),
            )?;
            let headers = self.get_headers(&self.cas_oauth_bearer_token_path)?;
            local_only_store
                .into_with_remote(RemoteStoreOptions {
                    provider: RemoteProvider::Reapi,
                    store_address: cas_server.to_owned(),
                    instance_name: self.remote_instance_name.clone(),
                    tls_config,
                    headers,
                    chunk_size_bytes: self.upload_chunk_bytes,
                    timeout: Duration::from_secs(30),
                    retries: self.store_rpc_retries,
                    concurrency_limit: self.store_rpc_concurrency,
                    batch_api_size_limit: self.store_batch_api_size_limit,
                })
                .await
        } else {
            Ok(local_only_store)
        }
    }
}

pub fn collection_from_keyvalues<Str, It, Col>(keyvalues: It) -> Col
where
    Str: AsRef<str>,
    It: Iterator<Item = Str>,
    Col: FromIterator<(String, String)>,
{
    keyvalues
        .map(|kv| {
            let mut parts = kv.as_ref().splitn(2, '=');
            (
                parts.next().unwrap().to_string(),
                parts.next().unwrap_or_default().to_string(),
            )
        })
        .collect()
}
