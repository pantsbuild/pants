// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::{collections::BTreeMap, time::Duration};

use hashing::Digest;
use mock::StubCAS;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use remote_provider_traits::{ActionCacheProvider, RemoteStoreOptions};

use super::action_cache::Provider;

async fn new_provider(cas: &StubCAS) -> Provider {
    Provider::new(RemoteStoreOptions {
        instance_name: None,
        store_address: cas.address(),
        tls_config: Default::default(),
        headers: BTreeMap::new(),
        concurrency_limit: 256,
        timeout: Duration::from_secs(2),
        retries: 0,
        batch_api_size_limit: 0,
        chunk_size_bytes: 0,
    })
    .await
    .unwrap()
}

#[tokio::test]
async fn get_action_result_existing() {
    let cas = StubCAS::empty();
    let provider = new_provider(&cas).await;

    let action_digest = Digest::of_bytes(b"get_action_cache test");
    let action_result = remexec::ActionResult {
        exit_code: 123,
        ..Default::default()
    };
    cas.action_cache
        .action_map
        .lock()
        .insert(action_digest.hash, action_result.clone());

    assert_eq!(
        provider.get_action_result(action_digest, "").await,
        Ok(Some(action_result))
    );
}

#[tokio::test]
async fn get_action_result_missing() {
    let cas = StubCAS::empty();
    let provider = new_provider(&cas).await;

    let action_digest = Digest::of_bytes(b"update_action_cache test");

    assert_eq!(
        provider.get_action_result(action_digest, "").await,
        Ok(None)
    );
}

#[tokio::test]
async fn get_action_result_grpc_error() {
    let cas = StubCAS::builder().ac_always_errors().build();
    let provider = new_provider(&cas).await;

    let action_digest = Digest::of_bytes(b"get_action_result_grpc_error test");

    let error = provider
        .get_action_result(action_digest, "")
        .await
        .expect_err("Want err");

    assert!(
        error.contains("unavailable"),
        "Bad error message, got: {error}"
    );
}

#[tokio::test]
async fn update_action_cache() {
    let cas = StubCAS::empty();
    let provider = new_provider(&cas).await;

    let action_digest = Digest::of_bytes(b"update_action_cache test");
    let action_result = remexec::ActionResult {
        exit_code: 123,
        ..Default::default()
    };

    provider
        .update_action_result(action_digest, action_result.clone())
        .await
        .unwrap();

    assert_eq!(
        cas.action_cache.action_map.lock()[&action_digest.hash],
        action_result
    );
}

#[tokio::test]
async fn update_action_cache_grpc_error() {
    let cas = StubCAS::builder().ac_always_errors().build();
    let provider = new_provider(&cas).await;

    let action_digest = Digest::of_bytes(b"update_action_cache_grpc_error test");
    let action_result = remexec::ActionResult {
        exit_code: 123,
        ..Default::default()
    };

    let error = provider
        .update_action_result(action_digest, action_result.clone())
        .await
        .expect_err("Want err");

    assert!(
        error.contains("unavailable"),
        "Bad error message, got: {error}"
    );
}
