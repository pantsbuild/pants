// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::ffi::OsString;
use std::path::PathBuf;
use std::time::Duration;

use bytes::Bytes;
use clap::Parser;
use tempfile::TempDir;
use testutil::data::TestData;

use crate::{LocalOptions, Store, StoreCliOpt};

#[test]
fn test_to_cli_args() {
    let opts = StoreCliOpt {
        local_store_path: Some(PathBuf::from("some/path")),
        local_store_files_max_size_bytes: Some(2001),
        local_store_directories_max_size_bytes: Some(2002),
        local_store_shard_count: Some(4),
        local_store_lease_time_secs: Some(2003),
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

#[test]
fn local_options_default_when_unset() {
    // A sandboxer started without the local store flags falls back to the defaults.
    let opts = StoreCliOpt::parse_from(["dummy_bin_name", "--local-store-path", "some/path"]);
    let defaults = LocalOptions::default();
    let local = opts.local_options();
    assert_eq!(local.files_max_size_bytes, defaults.files_max_size_bytes);
    assert_eq!(
        local.directories_max_size_bytes,
        defaults.directories_max_size_bytes
    );
    assert_eq!(local.shard_count, defaults.shard_count);
    assert_eq!(local.lease_time, defaults.lease_time);
}

#[test]
fn new_local_only_roundtrips_local_options() {
    let options = LocalOptions {
        files_max_size_bytes: 3001,
        directories_max_size_bytes: 3002,
        lease_time: Duration::from_secs(3003),
        shard_count: 2,
    };
    let local = StoreCliOpt::new_local_only(PathBuf::from("some/path"), &options).local_options();
    assert_eq!(local.files_max_size_bytes, 3001);
    assert_eq!(local.directories_max_size_bytes, 3002);
    assert_eq!(local.lease_time, Duration::from_secs(3003));
    assert_eq!(local.shard_count, 2);
}

/// A process that opens the store from `StoreCliOpt` (e.g. the sandboxer) must see what the
/// process that created those options stored, even when the store was not opened with defaults.
#[tokio::test]
async fn create_store_uses_local_options() {
    let dir = TempDir::new().unwrap();
    let options = || LocalOptions {
        shard_count: 1,
        ..LocalOptions::default()
    };
    let executor = task_executor::Executor::new();

    let writer =
        Store::local_only_with_options(executor.clone(), dir.path(), dir.path(), options())
            .unwrap();
    let testdata = TestData::roland();
    writer
        .store_file_bytes(testdata.bytes(), false)
        .await
        .unwrap();

    let reader = StoreCliOpt::new_local_only(dir.path().to_owned(), &options())
        .create_store(executor)
        .await
        .unwrap();
    let loaded = reader
        .load_file_bytes_with(testdata.digest(), Bytes::copy_from_slice)
        .await
        .unwrap();
    assert_eq!(loaded, testdata.bytes());
}
