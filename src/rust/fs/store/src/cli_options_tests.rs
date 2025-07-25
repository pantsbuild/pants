// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::ffi::OsString;
use std::path::PathBuf;

use clap::Parser;
use clap::command;

use crate::StoreCliOpt;

#[test]
fn test_to_cli_args() {
    let opts = StoreCliOpt {
        local_store_path: Some(PathBuf::from("some/path")),
        cas_server: Some("A CAS server".to_string()),
        remote_instance_name: Some("A remote instance name".to_string()),
        cas_root_ca_cert_file: Some(PathBuf::from("A CAS root CA cert file")),
        cas_client_certs_file: Some(PathBuf::from("A CAS client cert file")),
        cas_client_key_file: Some(PathBuf::from("A CAS client key file")),
        cas_oauth_bearer_token_path: Some(PathBuf::from("A CAS OAUTH bearer token path")),
        upload_chunk_bytes: 1001,
        store_rpc_retries: 1002,
        store_rpc_concurrency: 1004,
        store_batch_api_size_limit: 1005,
        store_batch_load_enabled: true,
        header: vec!["Header 1".to_string(), "Header 2".to_string()],
    };

    let cli_args = [
        &[OsString::from("dummy_bin_name")][..],
        &opts.to_cli_args()[..],
    ]
    .concat();

    #[derive(Parser)]
    #[command(name = "dummy")]
    struct DummyOpt {
        #[command(flatten)]
        store_options: StoreCliOpt,
    }

    let roundtrip_opts = DummyOpt::parse_from(cli_args.iter()).store_options;

    assert_eq!(opts, roundtrip_opts);
}
