// Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

#![deny(warnings)]
// Enable all clippy lints except for many of the pedantic ones. It's a shame this needs to be copied and pasted across crates, but there doesn't appear to be a way to include inner attributes from a common source.
#![deny(
  clippy::all,
  clippy::default_trait_access,
  clippy::expl_impl_clone_on_copy,
  clippy::if_not_else,
  clippy::needless_continue,
  clippy::unseparated_literal_suffix,
  clippy::used_underscore_binding
)]
// It is often more clear to show that nothing is being moved.
#![allow(clippy::match_ref_pats)]
// Subjective style.
#![allow(
  clippy::len_without_is_empty,
  clippy::redundant_field_names,
  clippy::too_many_arguments
)]
// Default isn't as big a deal as people seem to think it is.
#![allow(clippy::new_without_default, clippy::new_ret_no_self)]
// Arc<Mutex> can be more clear than needing to grok Orderings:
#![allow(clippy::mutex_atomic)]

use std::sync::Arc;

// Re-export these so that consumers don't have to know about the exact arrangement of underlying
// crates.
pub use remote_provider_traits::{
  ActionCacheProvider, ByteStoreProvider, LoadDestination, RemoteCacheProviderOptions,
  RemoteOptions,
};

const REAPI_ADDRESS_SCHEMAS: [&str; 4] = ["grpc://", "grpcs://", "http://", "https://"];

// TODO(#19902): a unified view of choosing a provider would be nice
pub async fn choose_byte_store_provider(
  options: RemoteOptions,
) -> Result<Arc<dyn ByteStoreProvider>, String> {
  let address = options.cas_address.clone();
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
  options: RemoteCacheProviderOptions,
) -> Result<Arc<dyn ActionCacheProvider>, String> {
  let address = options.action_cache_address.clone();

  // TODO: we shouldn't need to gin up a whole copy of this struct; it'd be better to have the two
  // set of remoting options managed together.
  let remote_options = RemoteOptions {
    cas_address: address.clone(),
    instance_name: options.instance_name.clone(),
    headers: options.headers.clone(),
    tls_config: grpc_util::tls::Config::new(
      options.root_ca_certs.clone(),
      options.mtls_data.clone(),
    )?,
    rpc_timeout: options.rpc_timeout,
    rpc_concurrency_limit: options.concurrency_limit,
    // TODO: these should either be passed through or not synthesized here
    chunk_size_bytes: 0,
    rpc_retries: 0,
    capabilities_cell_opt: None,
    batch_api_size_limit: 0,
  };

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
      remote_options,
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
        remote_options,
      )?,
    ))
  } else {
    Err(format!(
      "Cannot initialise remote action cache provider with address {address}, as the scheme is not supported",
    ))
  }
}
