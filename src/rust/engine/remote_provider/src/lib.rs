// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::sync::Arc;

// Re-export these so that consumers don't have to know about the exact arrangement of underlying
// crates.
pub use remote_provider_traits::{
    ActionCacheProvider, ByteStoreProvider, LoadDestination, RemoteProvider, RemoteStoreOptions,
};

// TODO(#19902): a unified view of choosing a provider would be nice
pub async fn choose_byte_store_provider(
    options: RemoteStoreOptions,
) -> Result<Arc<dyn ByteStoreProvider>, String> {
    let address = options.store_address.clone();
    match options.provider {
        RemoteProvider::Reapi => Ok(Arc::new(
            remote_provider_reapi::byte_store::Provider::new(options).await?,
        )),
        RemoteProvider::ExperimentalFile => {
            if let Some(path) = address.strip_prefix("file://") {
                // It's a bit weird to support local "file://" for a 'remote' store... but this is handy for
                // testing.
                Ok(Arc::new(remote_provider_opendal::Provider::fs(
                    path,
                    "byte-store".to_owned(),
                    options,
                )?))
            } else {
                Err(format!(
                    "file provider requires an address starting with file://, found {}",
                    options.store_address
                ))
            }
        }
        RemoteProvider::ExperimentalGithubActionsCache => Ok(Arc::new(
            remote_provider_opendal::Provider::github_actions_cache(
                &address,
                "byte-store".to_owned(),
                options,
            )?,
        )),
    }
}

pub async fn choose_action_cache_provider(
    options: RemoteStoreOptions,
) -> Result<Arc<dyn ActionCacheProvider>, String> {
    let address = options.store_address.clone();

    match options.provider {
        RemoteProvider::Reapi => Ok(Arc::new(
            remote_provider_reapi::action_cache::Provider::new(options).await?,
        )),
        RemoteProvider::ExperimentalFile => {
            if let Some(path) = address.strip_prefix("file://") {
                // It's a bit weird to support local "file://" for a 'remote' store... but this is handy for
                // testing.
                Ok(Arc::new(remote_provider_opendal::Provider::fs(
                    path,
                    "action-cache".to_owned(),
                    options,
                )?))
            } else {
                Err(format!(
                    "file provider requires an address starting with file://, found {}",
                    options.store_address
                ))
            }
        }
        RemoteProvider::ExperimentalGithubActionsCache => Ok(Arc::new(
            remote_provider_opendal::Provider::github_actions_cache(
                &address,
                "action-cache".to_owned(),
                options,
            )?,
        )),
    }
}
