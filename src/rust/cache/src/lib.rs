// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::Path;
use std::time::Duration;

use bytes::Bytes;
use grpc_util::prost::MessageExt;
use hashing::Digest;
use protos::gen::pants::cache::CacheKey;
use sharded_lmdb::ShardedLmdb;
use task_executor::Executor;

///
/// A persistent cache for small values and keys.
///
/// Keys are defined using `protos::pants::cache::CacheKey`, and are thus tagged Digests of larger
/// content. Values are untyped, but should also be very small via out-of-lining any large blobs
/// as Digests into other storage.
///
/// Because keys and values are always small, this class exposes a simpler API than our LMDB
/// access in general.
///
#[derive(Clone)]
pub struct PersistentCache {
    store: ShardedLmdb,
}

impl PersistentCache {
    pub fn new(
        store_dir: &Path,
        max_size_bytes: usize,
        executor: Executor,
        lease_time: Duration,
        shard_count: u8,
    ) -> Result<Self, String> {
        let store = ShardedLmdb::new(
            store_dir.join("cache"),
            max_size_bytes,
            executor,
            lease_time,
            shard_count,
        )
        .map_err(|err| format!("Could not initialize store for cache: {err:?}"))?;

        Ok(Self { store })
    }

    pub async fn store(&self, key: &CacheKey, value: Bytes) -> Result<(), String> {
        // NB: This is an unusual usage of the ShardedLmdb interface. In order for this to be a cache,
        // rather than storing the value under its _own_ Fingerprint, the value is stored under the
        // Fingerprint of the CacheKey.
        let fingerprint = Digest::of_bytes(&key.to_bytes()).hash;
        self.store.store_bytes(fingerprint, value, false).await?;
        Ok(())
    }

    pub async fn load(&self, key: &CacheKey) -> Result<Option<Bytes>, String> {
        let fingerprint = Digest::of_bytes(&key.to_bytes()).hash;
        self.store
            .load_bytes_with(fingerprint, move |bytes| Ok(Bytes::copy_from_slice(bytes)))
            .await
    }
}
