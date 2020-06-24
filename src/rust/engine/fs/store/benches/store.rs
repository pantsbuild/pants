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

use std::fs::File;
use std::io::{BufRead, BufReader};
use std::os::unix::ffi::OsStrExt;
use std::path::PathBuf;
use std::time::Duration;

use bytes::Bytes;
use futures::compat::Future01CompatExt;
use futures::future;
use hashing::Digest;
use task_executor::Executor;
use tempfile::TempDir;
use tokio::runtime::Runtime;

use store::{Snapshot, Store};

pub fn criterion_benchmark(c: &mut Criterion) {
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
        // NB: We take ownership of this child tempdir to avoid deleting things during the run.
        let dest = TempDir::new_in(parent_dest_path).unwrap().into_path();
        let _ = executor
          .block_on(store.materialize_directory(dest, digest).compat())
          .unwrap();
      })
    });
}

criterion_group!(benches, criterion_benchmark);
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

      // Drop empty or too-long candidates.
      let path_buf = clean_line.split_whitespace().collect::<PathBuf>();
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

  let digests = henries_paths
    .map(|mut path| {
      let store = store.clone();
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
      let store = store.clone();
      async move {
        let digests = future::try_join_all(digests).await?;
        Snapshot::merge_directories(store, digests).await
      }
    })
    .unwrap();

  (store, storedir, digest)
}
