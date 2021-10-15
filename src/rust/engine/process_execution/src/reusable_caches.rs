// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::BTreeMap;

use fs::RelativePath;
use hashing::Digest;
use store::{SnapshotOps, SnapshotOpsError, Store};

pub async fn merge_reusable_input_digests(
  store: &Store,
  input_digest: Digest,
  reusable_input_digests: BTreeMap<RelativePath, Digest>,
) -> Result<Digest, SnapshotOpsError> {
  let mut digests_to_merge = futures::future::try_join_all(
    reusable_input_digests
      .into_iter()
      .map(|(path, digest)| store.add_prefix(digest, path))
      .collect::<Vec<_>>(),
  )
  .await?;

  digests_to_merge.push(input_digest);

  store.merge(digests_to_merge).await
}
