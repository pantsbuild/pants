// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::BTreeMap;
use std::time::Duration;

use bytes::Bytes;
use grpc_util::prost::MessageExt;
use grpc_util::tls;
use hashing::Digest;
use opendal::services::Memory;
use prost::Message;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remote_provider_traits::{ActionCacheProvider, RemoteStoreOptions};

use super::Provider;

const BASE: &str = "opendal-testing-base";

fn test_path(digest: Digest) -> String {
    let fingerprint = digest.hash.to_string();
    format!(
        "{}/{}/{}/{}",
        BASE,
        &fingerprint[0..2],
        &fingerprint[2..4],
        fingerprint
    )
}

fn remote_options() -> RemoteStoreOptions {
    RemoteStoreOptions {
        store_address: "".to_owned(),
        instance_name: None,
        tls_config: tls::Config::default(),
        headers: BTreeMap::new(),
        chunk_size_bytes: 10000,
        rpc_timeout: Duration::from_secs(5),
        rpc_retries: 1,
        rpc_concurrency_limit: 256,
        batch_api_size_limit: 10000,
    }
}

fn new_provider() -> Provider {
    Provider::new(Memory::default(), BASE.to_owned(), remote_options()).unwrap()
}

async fn write_test_data(provider: &Provider, digest: Digest, data: remexec::ActionResult) {
    provider
        .operator
        .write(&test_path(digest), data.to_bytes())
        .await
        .unwrap()
}

#[tokio::test]
async fn get_action_result_existing() {
    let provider = new_provider();

    let action_digest = Digest::of_bytes(b"get_action_cache test");
    let action_result = remexec::ActionResult {
        exit_code: 123,
        ..Default::default()
    };
    write_test_data(&provider, action_digest, action_result.clone()).await;

    assert_eq!(
        provider.get_action_result(action_digest, "").await,
        Ok(Some(action_result))
    );
}

#[tokio::test]
async fn get_action_result_missing() {
    let provider = new_provider();

    let action_digest = Digest::of_bytes(b"update_action_cache test");

    assert_eq!(
        provider.get_action_result(action_digest, "").await,
        Ok(None)
    );
}

#[tokio::test]
async fn update_action_cache() {
    let provider = new_provider();

    let action_digest = Digest::of_bytes(b"update_action_cache test");
    let action_result = remexec::ActionResult {
        exit_code: 123,
        ..Default::default()
    };

    provider
        .update_action_result(action_digest, action_result.clone())
        .await
        .unwrap();

    let stored = provider
        .operator
        .read(&test_path(action_digest))
        .await
        .unwrap();
    assert_eq!(
        remexec::ActionResult::decode(Bytes::from(stored)).unwrap(),
        action_result
    );
}
