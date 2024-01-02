// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use criterion::{criterion_group, criterion_main, Criterion};

use std::collections::{BTreeSet, HashSet};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::os::unix::ffi::OsStrExt;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use fs::{
    DirectoryDigest, File, GitignoreStyleExcludes, GlobExpansionConjunction, PathStat, Permissions,
    PosixFS, PreparedPathGlobs, StrictGlobMatching,
};
use hashing::EMPTY_DIGEST;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use task_executor::Executor;
use tempfile::TempDir;

use store::{OneOffStoreFileByDigest, Snapshot, SnapshotOps, Store, SubsetParams};

fn executor() -> Executor {
    Executor::new_owned(num_cpus::get(), num_cpus::get() * 4, || ()).unwrap()
}

pub fn criterion_benchmark_materialize(c: &mut Criterion) {
    // Create an executor, store containing the stuff to materialize, and a digest for the stuff.
    // To avoid benchmarking the deleting of things, we create a parent temporary directory (which
    // will be deleted at the end of the benchmark) and then skip deletion of the per-run directories.
    let executor = executor();

    let mut cgroup = c.benchmark_group("materialize_directory");

    for perms in [Permissions::ReadOnly, Permissions::Writable] {
        for (count, size) in [(100, 100), (20, 10_000_000), (1, 200_000_000), (10000, 100)] {
            let (store, _tempdir, digest) = snapshot(&executor, count, size);
            let parent_dest = TempDir::new().unwrap();
            let parent_dest_path = parent_dest.path();

            cgroup
                .sample_size(10)
                .measurement_time(Duration::from_secs(30))
                .bench_function(
                    format!("materialize_directory({:?}, {}, {})", perms, count, size),
                    |b| {
                        b.iter(|| {
                            // NB: We forget this child tempdir to avoid deleting things during the run.
                            let new_temp = TempDir::new_in(parent_dest_path).unwrap();
                            let dest = new_temp.path().to_path_buf();
                            std::mem::forget(new_temp);
                            executor
                                .block_on(store.materialize_directory(
                                    dest,
                                    parent_dest_path,
                                    digest.clone(),
                                    false,
                                    &BTreeSet::new(),
                                    perms,
                                ))
                                .unwrap();
                        })
                    },
                );
        }
    }
}

///
/// NB: More accurately, this benchmarks `Snapshot::from_path_stats`, which avoids
/// filesystem traversal overheads and focuses on digesting/capturing.
///
pub fn criterion_benchmark_snapshot_capture(c: &mut Criterion) {
    let executor = executor();

    let mut cgroup = c.benchmark_group("snapshot_capture");

    // The number of files, file size, whether the inputs should be assumed to be immutable, and the
    // number of times to capture (only the first capture actually stores anything: the rest should
    // ignore the duplicated data.)
    for params in [
        (100, 100, false, 100),
        (20, 10_000_000, true, 10),
        (1, 200_000_000, true, 10),
    ] {
        let (count, size, immutable, captures) = params;
        let storedir = TempDir::new().unwrap();
        let store = Store::local_only(executor.clone(), storedir.path()).unwrap();
        let (tempdir, path_stats) = tempdir_containing(count, size);
        let posix_fs = Arc::new(
            PosixFS::new(
                tempdir.path(),
                GitignoreStyleExcludes::empty(),
                executor.clone(),
            )
            .unwrap(),
        );
        cgroup
            .sample_size(10)
            .measurement_time(Duration::from_secs(30))
            .bench_function(format!("snapshot_capture({:?})", params), |b| {
                b.iter(|| {
                    for _ in 0..captures {
                        let _ = executor
                            .block_on(Snapshot::from_path_stats(
                                OneOffStoreFileByDigest::new(
                                    store.clone(),
                                    posix_fs.clone(),
                                    immutable,
                                ),
                                path_stats.clone(),
                            ))
                            .unwrap();
                    }
                })
            });
    }
}

pub fn criterion_benchmark_subset_wildcard(c: &mut Criterion) {
    let executor = executor();
    // NB: We use a much larger snapshot size compared to the materialize benchmark!
    let (store, _tempdir, digest) = snapshot(&executor, 1000, 100);

    let mut cgroup = c.benchmark_group("digest_subset");

    cgroup
        .sample_size(10)
        .measurement_time(Duration::from_secs(80))
        .bench_function("wildcard", |b| {
            b.iter(|| {
                let get_subset = store.subset(
                    digest.clone(),
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
    let executor = executor();
    let num_files: usize = 4000;
    let (store, _tempdir, digest) = snapshot(&executor, num_files, 100);

    // Modify half of the files in the top-level directory by setting them to have the empty
    // fingerprint (zero content).
    executor
        .block_on(store.ensure_directory_digest_persisted(digest.clone()))
        .unwrap();
    let directory = executor
        .block_on(store.load_directory(digest.as_digest()))
        .unwrap();
    let mut all_file_nodes = directory.files.to_vec();
    let mut file_nodes_to_modify = all_file_nodes.split_off(all_file_nodes.len() / 2);
    for file_node in file_nodes_to_modify.iter_mut() {
        file_node.digest = Some(remexec::Digest {
            hash: EMPTY_DIGEST.hash.to_hex(),
            size_bytes: 0,
        });
    }
    let modified_file_names: HashSet<String> = file_nodes_to_modify
        .iter()
        .map(|file_node| file_node.name.to_string())
        .collect();

    let bazel_modified_files_directory = remexec::Directory {
        files: all_file_nodes
            .iter()
            .cloned()
            .chain(file_nodes_to_modify)
            .collect(),
        directories: directory.directories.clone(),
        ..remexec::Directory::default()
    };

    let modified_digest = executor
        .block_on(store.record_directory(&bazel_modified_files_directory, true))
        .unwrap();

    let bazel_removed_files_directory = remexec::Directory {
        files: all_file_nodes
            .into_iter()
            .filter(|file_node| !modified_file_names.contains(&file_node.name))
            .collect(),
        directories: directory.directories.clone(),
        ..remexec::Directory::default()
    };
    let removed_digest = executor
        .block_on(store.record_directory(&bazel_removed_files_directory, true))
        .unwrap();

    // NB: We benchmark with trees that are already held in memory, since that's the expected case in
    // production.
    let removed_digest = executor
        .block_on(store.load_directory_digest(removed_digest))
        .unwrap();
    let modified_digest = executor
        .block_on(store.load_directory_digest(modified_digest))
        .unwrap();

    let mut cgroup = c.benchmark_group("snapshot_merge");

    cgroup
        .sample_size(10)
        .measurement_time(Duration::from_secs(80))
        .bench_function("snapshot_merge", |b| {
            b.iter(|| {
                // Merge the old and the new snapshot together, allowing any file to be duplicated.
                let old_first = executor
                    .block_on(store.merge(vec![removed_digest.clone(), modified_digest.clone()]))
                    .unwrap();

                // Test the performance of either ordering of snapshots.
                let new_first = executor
                    .block_on(store.merge(vec![modified_digest.clone(), removed_digest.clone()]))
                    .unwrap();

                assert_eq!(old_first, new_first);
            })
        });
}

criterion_group!(
    benches,
    criterion_benchmark_materialize,
    criterion_benchmark_snapshot_capture,
    criterion_benchmark_subset_wildcard,
    criterion_benchmark_merge
);
criterion_main!(benches);

///
/// Creates and returns a TempDir containing the given number of files, each approximately of size
/// file_target_size.
///
fn tempdir_containing(max_files: usize, file_target_size: usize) -> (TempDir, Vec<PathStat>) {
    let henries_lines = {
        let f = std::fs::File::open(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("..")
                .join("..")
                .join("testutil")
                .join("src")
                .join("all_the_henries.txt"),
        )
        .expect("Error opening all_the_henries");
        BufReader::new(f).lines()
    };

    let mut produced = HashSet::new();
    let paths = henries_lines
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
            let mut path_buf = clean_line.split_whitespace().collect::<PathBuf>();
            // Drop empty or too-long candidates.
            let components_too_long = path_buf.components().any(|c| c.as_os_str().len() > 255);
            if components_too_long
                || path_buf.as_os_str().is_empty()
                || path_buf.as_os_str().len() > 512
            {
                None
            } else {
                // We add an extension to files to avoid collisions with directories (which are created
                // implicitly based on leading components).
                path_buf.set_extension("txt");
                Some(PathStat::file(
                    path_buf.clone(),
                    File {
                        path: path_buf,
                        is_executable: false,
                    },
                ))
            }
        })
        .filter(move |path| produced.insert(path.clone()))
        .take(max_files)
        .collect::<Vec<_>>();

    let tempdir = TempDir::new().unwrap();
    for path in &paths {
        // We use the (repeated) path as the content as well.
        let abs_path = tempdir.path().join(path.path());
        if let Some(parent) = abs_path.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        let mut f = BufWriter::new(std::fs::File::create(abs_path).unwrap());
        let bytes = path.path().as_os_str().as_bytes();
        let lines_to_write = file_target_size / bytes.len();
        for _ in 0..lines_to_write {
            f.write_all(bytes).unwrap();
            f.write_all(b"\n").unwrap();
        }
    }
    (tempdir, paths)
}

///
/// Returns a Store (and the TempDir it is stored in) and a Digest for a nested directory
/// containing the given number of files, each with roughly the given size.
///
fn snapshot(
    executor: &Executor,
    max_files: usize,
    file_target_size: usize,
) -> (Store, TempDir, DirectoryDigest) {
    // NB: We create the files in a tempdir rather than in memory in order to allow for more
    // realistic benchmarking involving large files. The tempdir is dropped at the end of this method
    // (after everything has been captured out of it).
    let (tempdir, path_stats) = tempdir_containing(max_files, file_target_size);
    let storedir = TempDir::new().unwrap();
    let store = Store::local_only(executor.clone(), storedir.path()).unwrap();

    let store2 = store.clone();
    let digest = executor
        .block_on(async move {
            let posix_fs = PosixFS::new(
                tempdir.path(),
                GitignoreStyleExcludes::empty(),
                executor.clone(),
            )
            .unwrap();
            Snapshot::from_path_stats(
                OneOffStoreFileByDigest::new(store2, Arc::new(posix_fs), true),
                path_stats,
            )
            .await
        })
        .unwrap()
        .into();

    (store, storedir, digest)
}
