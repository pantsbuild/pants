// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
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
  // TODO: Falsely triggers for async/await:
  //   see https://github.com/rust-lang/rust-clippy/issues/5360
  // clippy::used_underscore_binding
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

use criterion::{criterion_group, criterion_main, Criterion};

use std::collections::HashSet;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::os::unix::ffi::OsStrExt;
use std::path::PathBuf;
use std::time::Duration;

use bazel_protos::remote_execution as remexec;
use bytes::Bytes;
use fs::{GlobExpansionConjunction, PreparedPathGlobs, StrictGlobMatching};
use futures::compat::Future01CompatExt;
use futures::future;
use hashing::{Digest, EMPTY_DIGEST};
use protobuf;
use task_executor::Executor;
use tempfile::TempDir;
use tokio::runtime::Runtime;

use store::{SnapshotOps, Store, SubsetParams};

pub fn criterion_benchmark_materialize(c: &mut Criterion) {
  // Create an executor, store containing the stuff to materialize, and a digest for the stuff.
  // To avoid benchmarking the deleting of things, we create a parent temporary directory (which
  // will be deleted at the end of the benchmark) and then skip deletion of the per-run directories.
  let rt = Runtime::new().unwrap();
  let executor = Executor::new(rt.handle().clone());
  let (store, _tempdir, digest) = large_snapshot(&executor, 100);
  let parent_dest = TempDir::new().unwrap();
  let parent_dest_path = parent_dest.path();

  let mut cgroup = c.benchmark_group("materialize_directory");

  cgroup
    .sample_size(10)
    .measurement_time(Duration::from_secs(60))
    .bench_function("materialize_directory", |b| {
      b.iter(|| {
        // NB: We forget this child tempdir to avoid deleting things during the run.
        let new_temp = TempDir::new_in(parent_dest_path).unwrap();
        let dest = new_temp.path().to_path_buf();
        std::mem::forget(new_temp);
        let _ = executor
          .block_on(store.materialize_directory(dest, digest).compat())
          .unwrap();
      })
    });
}

pub fn criterion_benchmark_subset_wildcard(c: &mut Criterion) {
  let rt = Runtime::new().unwrap();
  let executor = Executor::new(rt.handle().clone());
  // NB: We use a much larger snapshot size compared to the materialize benchmark!
  let (store, _tempdir, digest) = large_snapshot(&executor, 1000);

  let mut cgroup = c.benchmark_group("digest_subset");

  cgroup
    .sample_size(10)
    .measurement_time(Duration::from_secs(80))
    .bench_function("wildcard", |b| {
      b.iter(|| {
        let get_subset = store.subset(
          digest,
          SubsetParams {
            globs: PreparedPathGlobs::create(
              vec!["**/*".to_string()],
              StrictGlobMatching::Ignore,
              GlobExpansionConjunction::AllMatch,
            )
            .unwrap(),
          },
        );
        let _ = executor.block_on(get_subset).unwrap();
      })
    });
}

pub fn criterion_benchmark_merge(c: &mut Criterion) {
  let rt = Runtime::new().unwrap();
  let executor = Executor::new(rt.handle().clone());
  let num_files: usize = 4000;
  let (store, _tempdir, digest) = large_snapshot(&executor, num_files);

  let (directory, _metadata) = executor
    .block_on(store.load_directory(digest))
    .unwrap()
    .unwrap();
  // Modify half of the files in the top-level directory by setting them to have the empty
  // fingerprint (zero content).
  let mut all_file_nodes = directory.get_files().to_vec();
  let mut file_nodes_to_modify = all_file_nodes.split_off(all_file_nodes.len() / 2);
  for file_node in file_nodes_to_modify.iter_mut() {
    let mut empty_bazel_digest = remexec::Digest::new();
    empty_bazel_digest.set_hash(EMPTY_DIGEST.0.to_hex());
    empty_bazel_digest.set_size_bytes(0);
    file_node.set_digest(empty_bazel_digest);
  }
  let modified_file_names: HashSet<String> = file_nodes_to_modify
    .iter()
    .map(|file_node| file_node.get_name().to_string())
    .collect();

  let mut bazel_modified_files_directory = remexec::Directory::new();
  bazel_modified_files_directory.set_files(protobuf::RepeatedField::from_vec(
    all_file_nodes
      .iter()
      .cloned()
      .chain(file_nodes_to_modify.into_iter())
      .collect(),
  ));
  bazel_modified_files_directory.set_directories(directory.directories.clone());

  let modified_digest = executor
    .block_on(store.record_directory(&bazel_modified_files_directory, true))
    .unwrap();

  let mut bazel_removed_files_directory = remexec::Directory::new();
  bazel_removed_files_directory.set_files(protobuf::RepeatedField::from_vec(
    all_file_nodes
      .into_iter()
      .filter(|file_node| !modified_file_names.contains(file_node.get_name()))
      .collect(),
  ));
  bazel_removed_files_directory.set_directories(directory.directories.clone());
  let removed_digest = executor
    .block_on(store.record_directory(&bazel_removed_files_directory, true))
    .unwrap();

  let mut cgroup = c.benchmark_group("snapshot_merge");

  cgroup
    .sample_size(10)
    .measurement_time(Duration::from_secs(80))
    .bench_function("snapshot_merge", |b| {
      b.iter(|| {
        // Merge the old and the new snapshot together, allowing any file to be duplicated.
        let old_first: Digest = executor
          .block_on(store.merge(vec![removed_digest, modified_digest]))
          .unwrap();

        // Test the performance of either ordering of snapshots.
        let new_first: Digest = executor
          .block_on(store.merge(vec![modified_digest, removed_digest]))
          .unwrap();

        assert_eq!(old_first, new_first);
      })
    });
}

criterion_group!(
  benches,
  criterion_benchmark_materialize,
  criterion_benchmark_subset_wildcard,
  criterion_benchmark_merge
);
criterion_main!(benches);

///
/// Returns a Store (and the TempDir it is stored in) and a Digest for a nested directory
/// containing one file per line in "all_the_henries".
///
pub fn large_snapshot(executor: &Executor, max_files: usize) -> (Store, TempDir, Digest) {
  let henries_lines = {
    let f = File::open(
      PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("testdata")
        .join("all_the_henries"),
    )
    .expect("Error opening all_the_henries");
    BufReader::new(f).lines()
  };

  let henries_paths = henries_lines
    .filter_map(|line| {
      // Clean up to lowercase ascii.
      let clean_line = line
        .expect("Failed to read from all_the_henries")
        .trim()
        .chars()
        .filter_map(|c| {
          if c.is_ascii_alphanumeric() {
            Some(c.to_ascii_lowercase())
          } else if c.is_ascii_whitespace() {
            Some(' ')
          } else {
            None
          }
        })
        .collect::<String>();

      // NB: Split the line by whitespace, then accumulate a PathBuf using each word as a path
      // component!
      let path_buf = clean_line.split_whitespace().collect::<PathBuf>();
      // Drop empty or too-long candidates.
      let components_too_long = path_buf.components().any(|c| c.as_os_str().len() > 255);
      if components_too_long || path_buf.as_os_str().is_empty() || path_buf.as_os_str().len() > 512
      {
        None
      } else {
        Some(path_buf)
      }
    })
    .take(max_files);

  let storedir = TempDir::new().unwrap();
  let store = Store::local_only(executor.clone(), storedir.path()).unwrap();

  let store2 = store.clone();
  let digests = henries_paths
    .map(|mut path| {
      let store = store2.clone();
      async move {
        // We use the path as the content as well: would be interesting to make this tunable.
        let content = Bytes::from(path.as_os_str().as_bytes());
        // We add an extension to files to avoid collisions with directories (which are created
        // implicitly based on leading components).
        path.set_extension("txt");
        let digest = store.store_file_bytes(content, true).await?;
        let snapshot = store.snapshot_of_one_file(path, digest, false).await?;
        let res: Result<_, String> = Ok(snapshot.digest);
        res
      }
    })
    .collect::<Vec<_>>();

  let digest = executor
    .block_on({
      async move {
        let digests = future::try_join_all(digests).await?;
        store2.merge(digests).await
      }
    })
    .unwrap();

  (store, storedir, digest)
}
