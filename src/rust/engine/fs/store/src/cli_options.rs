// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::{collections::BTreeMap, ffi::OsString, path::PathBuf, time::Duration};

use clap::Parser;
use remote_provider::{RemoteProvider, RemoteStoreOptions};
use task_executor::Executor;

use crate::Store;
#[derive(Debug, Clone, Eq, PartialEq, Parser)]
pub struct StoreCliOpt {
    ///Path to lmdb directory used for local file storage.
    #[arg(long)]
    pub local_store_path: Option<PathBuf>,

    /// The host:port of the gRPC CAS server to connect to.
    #[arg(long)]
    pub cas_server: Option<String>,

    #[arg(long)]
    pub remote_instance_name: Option<String>,

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
    pub fn new_local_only(local_store_path: PathBuf) -> Self {
        Self {
            local_store_path: Some(local_store_path),
            cas_server: None,
            remote_instance_name: None,
            cas_root_ca_cert_file: None,
            cas_client_certs_file: None,
            cas_client_key_file: None,
            cas_oauth_bearer_token_path: None,
            upload_chunk_bytes: 0,
            store_rpc_retries: 0,
            store_rpc_concurrency: 0,
            store_batch_api_size_limit: 0,
            header: vec![],
        }
    }

    pub fn to_cli_args(&self) -> Vec<OsString> {
        let mut ret: Vec<OsString> = vec![];

        fn maybe_push_arg<S: Into<OsString> + std::convert::AsRef<std::ffi::OsStr>>(
            args: &mut Vec<OsString>,
            flag: &str,
            arg: &Option<S>,
        ) {
            if let Some(val) = arg {
                push_arg(args, flag, val);
            }
        }

        fn push_arg_if_nz(args: &mut Vec<OsString>, flag: &str, val: usize) {
            if val != 0 {
                push_arg(args, flag, &val.to_string());
            }
        }

        fn push_arg<S: Into<OsString> + std::convert::AsRef<std::ffi::OsStr>>(
            args: &mut Vec<OsString>,
            flag: &str,
            val: &S,
        ) {
            args.push(flag.into());
            args.push(val.into());
        }

        maybe_push_arg(&mut ret, "--local-store-path", &self.local_store_path);
        maybe_push_arg(&mut ret, "--cas-server", &self.cas_server);
        maybe_push_arg(
            &mut ret,
            "--remote-instance-name",
            &self.remote_instance_name,
        );
        maybe_push_arg(
            &mut ret,
            "--cas-root-ca-cert-file",
            &self.cas_root_ca_cert_file,
        );
        maybe_push_arg(
            &mut ret,
            "--cas-client-certs-file",
            &self.cas_client_certs_file,
        );
        maybe_push_arg(&mut ret, "--cas-client-key-file", &self.cas_client_key_file);
        maybe_push_arg(
            &mut ret,
            "--cas-oauth-bearer-token-path",
            &self.cas_oauth_bearer_token_path,
        );

        push_arg_if_nz(&mut ret, "--upload-chunk-bytes", self.upload_chunk_bytes);
        push_arg_if_nz(&mut ret, "--store-rpc-retries", self.store_rpc_retries);
        push_arg_if_nz(
            &mut ret,
            "--store-rpc-concurrency",
            self.store_rpc_concurrency,
        );
        push_arg_if_nz(
            &mut ret,
            "--store-batch-api-size-limit",
            self.store_batch_api_size_limit,
        );

        for header in self.header.iter() {
            ret.push("--header".into());
            ret.push(header.into());
        }

        ret
    }

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
