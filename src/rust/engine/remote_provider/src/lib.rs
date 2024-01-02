// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::Arc;

// Re-export these so that consumers don't have to know about the exact arrangement of underlying
// crates.
pub use remote_provider_traits::{
    ActionCacheProvider, ByteStoreProvider, LoadDestination, RemoteStoreOptions,
};

const REAPI_ADDRESS_SCHEMAS: [&str; 4] = ["grpc://", "grpcs://", "http://", "https://"];

// TODO(#19902): a unified view of choosing a provider would be nice
pub async fn choose_byte_store_provider(
    options: RemoteStoreOptions,
) -> Result<Arc<dyn ByteStoreProvider>, String> {
    let address = options.store_address.clone();
    if REAPI_ADDRESS_SCHEMAS.iter().any(|s| address.starts_with(s)) {
        Ok(Arc::new(
            remote_provider_reapi::byte_store::Provider::new(options).await?,
        ))
    } else if let Some(path) = address.strip_prefix("file://") {
        // It's a bit weird to support local "file://" for a 'remote' store... but this is handy for
        // testing.
        Ok(Arc::new(remote_provider_opendal::Provider::fs(
            path,
            "byte-store".to_owned(),
            options,
        )?))
    } else if let Some(url) = address.strip_prefix("github-actions-cache+") {
        // This is relying on python validating that it was set as `github-actions-cache+https://...` so
        // incorrect values could easily slip through here and cause downstream confusion. We're
        // intending to change the approach (https://github.com/pantsbuild/pants/issues/19902) so this
        // is tolerable for now.
        Ok(Arc::new(
            remote_provider_opendal::Provider::github_actions_cache(
                url,
                "byte-store".to_owned(),
                options,
            )?,
        ))
    } else {
        Err(format!(
      "Cannot initialise remote byte store provider with address {address}, as the scheme is not supported",
    ))
    }
}

pub async fn choose_action_cache_provider(
    options: RemoteStoreOptions,
) -> Result<Arc<dyn ActionCacheProvider>, String> {
    let address = options.store_address.clone();

    if REAPI_ADDRESS_SCHEMAS.iter().any(|s| address.starts_with(s)) {
        Ok(Arc::new(
            remote_provider_reapi::action_cache::Provider::new(options).await?,
        ))
    } else if let Some(path) = address.strip_prefix("file://") {
        // It's a bit weird to support local "file://" for a 'remote' store... but this is handy for
        // testing.
        Ok(Arc::new(remote_provider_opendal::Provider::fs(
            path,
            "action-cache".to_owned(),
            options,
        )?))
    } else if let Some(url) = address.strip_prefix("github-actions-cache+") {
        // This is relying on python validating that it was set as `github-actions-cache+https://...` so
        // incorrect values could easily slip through here and cause downstream confusion. We're
        // intending to change the approach (https://github.com/pantsbuild/pants/issues/19902) so this
        // is tolerable for now.
        Ok(Arc::new(
            remote_provider_opendal::Provider::github_actions_cache(
                url,
                "action-cache".to_owned(),
                options,
            )?,
        ))
    } else {
        Err(format!(
      "Cannot initialise remote action cache provider with address {address}, as the scheme is not supported",
    ))
    }
}
