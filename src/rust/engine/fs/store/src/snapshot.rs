// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::Store;
use bazel_protos;
use boxfuture::{try_future, BoxFuture, Boxable};
use fs::{Dir, File, GlobMatching, PathGlobs, PathStat, PosixFS, SymlinkBehavior};
use futures::future::{self, join_all};
use futures::Future;
use hashing::{Digest, EMPTY_DIGEST};
use indexmap::{self, IndexMap};
use itertools::Itertools;
use protobuf;
use std::ffi::OsString;
use std::fmt;
use std::iter::Iterator;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use workunit_store::WorkUnitStore;

#[derive(Eq, Hash, PartialEq)]
pub struct Snapshot {
  pub digest: Digest,
  pub path_stats: Vec<PathStat>,
}

impl Snapshot {
  pub fn empty() -> Snapshot {
    Snapshot {
      digest: EMPTY_DIGEST,
      path_stats: vec![],
    }
  }

  pub fn from_path_stats<
    S: StoreFileByDigest<Error> + Sized + Clone,
    Error: fmt::Debug + 'static + Send,
  >(
    store: Store,
    file_digester: &S,
    mut path_stats: Vec<PathStat>,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Snapshot, String> {
    path_stats.sort_by(|a, b| a.path().cmp(b.path()));

    // The helper assumes that if a Path has multiple children, it must be a directory.
    // Proactively error if we run into identically named files, because otherwise we will treat
    // them like empty directories.
    let pre_dedupe_len = path_stats.len();
    path_stats.dedup_by(|a, b| a.path() == b.path());
    if path_stats.len() != pre_dedupe_len {
      return future::err(format!(
        "Snapshots must be constructed from unique path stats; got duplicates in {:?}",
        path_stats
      ))
      .to_boxed();
    }
    Snapshot::ingest_directory_from_sorted_path_stats(
      store,
      file_digester,
      &path_stats,
      workunit_store,
    )
    .map(|digest| Snapshot { digest, path_stats })
    .to_boxed()
  }

  pub fn from_digest(
    store: Store,
    digest: Digest,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Snapshot, String> {
    store
      .walk(
        digest,
        |_, path_so_far, _, directory| {
          let mut path_stats = Vec::new();
          path_stats.extend(directory.get_directories().iter().map(move |dir_node| {
            let path = path_so_far.join(dir_node.get_name());
            PathStat::dir(path.clone(), Dir(path))
          }));
          path_stats.extend(directory.get_files().iter().map(move |file_node| {
            let path = path_so_far.join(file_node.get_name());
            PathStat::file(
              path.clone(),
              File {
                path,
                is_executable: file_node.is_executable,
              },
            )
          }));
          future::ok(path_stats).to_boxed()
        },
        workunit_store,
      )
      .map(move |path_stats_per_directory| {
        let mut path_stats =
          Iterator::flatten(path_stats_per_directory.into_iter().map(Vec::into_iter))
            .collect::<Vec<_>>();
        path_stats.sort_by(|l, r| l.path().cmp(&r.path()));
        Snapshot { digest, path_stats }
      })
      .to_boxed()
  }

  pub fn digest_from_path_stats<
    S: StoreFileByDigest<Error> + Sized + Clone,
    Error: fmt::Debug + 'static + Send,
  >(
    store: Store,
    file_digester: &S,
    path_stats: &[PathStat],
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Digest, String> {
    let mut sorted_path_stats = path_stats.to_owned();
    sorted_path_stats.sort_by(|a, b| a.path().cmp(b.path()));
    Snapshot::ingest_directory_from_sorted_path_stats(
      store,
      file_digester,
      &sorted_path_stats,
      workunit_store,
    )
  }

  fn ingest_directory_from_sorted_path_stats<
    S: StoreFileByDigest<Error> + Sized + Clone,
    Error: fmt::Debug + 'static + Send,
  >(
    store: Store,
    file_digester: &S,
    path_stats: &[PathStat],
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Digest, String> {
    let mut file_futures: Vec<BoxFuture<bazel_protos::remote_execution::FileNode, String>> =
      Vec::new();
    let mut dir_futures: Vec<BoxFuture<bazel_protos::remote_execution::DirectoryNode, String>> =
      Vec::new();

    for (first_component, group) in &path_stats
      .iter()
      .cloned()
      .group_by(|s| s.path().components().next().unwrap().as_os_str().to_owned())
    {
      let mut path_group: Vec<PathStat> = group.collect();
      if path_group.len() == 1 && path_group[0].path().components().count() == 1 {
        // Exactly one entry with exactly one component indicates either a file in this directory,
        // or an empty directory.
        // If the child is a non-empty directory, or a file therein, there must be multiple
        // PathStats with that prefix component, and we will handle that in the recursive
        // save_directory call.

        match path_group.pop().unwrap() {
          PathStat::File { ref stat, .. } => {
            let is_executable = stat.is_executable;
            file_futures.push(
              file_digester
                .clone()
                .store_by_digest(stat.clone(), workunit_store.clone())
                .map_err(|e| format!("{:?}", e))
                .and_then(move |digest| {
                  let mut file_node = bazel_protos::remote_execution::FileNode::new();
                  file_node.set_name(osstring_as_utf8(first_component)?);
                  file_node.set_digest((&digest).into());
                  file_node.set_is_executable(is_executable);
                  Ok(file_node)
                })
                .to_boxed(),
            );
          }
          PathStat::Dir { .. } => {
            // Because there are no children of this Dir, it must be empty.
            dir_futures.push(
              store
                .record_directory(&bazel_protos::remote_execution::Directory::new(), true)
                .map(move |digest| {
                  let mut directory_node = bazel_protos::remote_execution::DirectoryNode::new();
                  directory_node.set_name(osstring_as_utf8(first_component).unwrap());
                  directory_node.set_digest((&digest).into());
                  directory_node
                })
                .to_boxed(),
            );
          }
        }
      } else {
        dir_futures.push(
          // TODO: Memoize this in the graph
          Snapshot::ingest_directory_from_sorted_path_stats(
            store.clone(),
            file_digester,
            &paths_of_child_dir(path_group),
            workunit_store.clone(),
          )
          .and_then(move |digest| {
            let mut dir_node = bazel_protos::remote_execution::DirectoryNode::new();
            dir_node.set_name(osstring_as_utf8(first_component)?);
            dir_node.set_digest((&digest).into());
            Ok(dir_node)
          })
          .to_boxed(),
        );
      }
    }
    join_all(dir_futures)
      .join(join_all(file_futures))
      .and_then(move |(dirs, files)| {
        let mut directory = bazel_protos::remote_execution::Directory::new();
        directory.set_directories(protobuf::RepeatedField::from_vec(dirs));
        directory.set_files(protobuf::RepeatedField::from_vec(files));
        store.record_directory(&directory, true)
      })
      .to_boxed()
  }

  ///
  /// Given N Snapshots, returns a new Snapshot that merges them.
  ///
  /// Any files that exist in multiple Snapshots will cause this method to fail: the assumption
  /// behind this behaviour is that almost any colliding file would represent a Rule implementation
  /// error, and in cases where overwriting a file is desirable, explicitly removing a duplicated
  /// copy should be straightforward.
  ///
  pub fn merge(
    store: Store,
    snapshots: &[Snapshot],
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Snapshot, String> {
    // We dedupe PathStats by their symbolic names, as those will be their names within the
    // `Directory` structure. Only `Dir+Dir` collisions are legal.
    let path_stats = {
      let mut uniq_paths: IndexMap<PathBuf, PathStat> = IndexMap::new();
      for path_stat in Iterator::flatten(snapshots.iter().map(|s| s.path_stats.iter().cloned())) {
        match uniq_paths.entry(path_stat.path().to_owned()) {
          indexmap::map::Entry::Occupied(e) => match (&path_stat, e.get()) {
            (&PathStat::Dir { .. }, &PathStat::Dir { .. }) => (),
            (x, y) => {
              return future::err(format!(
                "Snapshots contained duplicate path: {:?} vs {:?}",
                x, y
              ))
              .to_boxed();
            }
          },
          indexmap::map::Entry::Vacant(v) => {
            v.insert(path_stat);
          }
        }
      }
      uniq_paths.into_iter().map(|(_, v)| v).collect()
    };
    // Recursively merge the Digests in the Snapshots.
    Self::merge_directories(
      store,
      snapshots.iter().map(|s| s.digest).collect(),
      workunit_store,
    )
    .map(move |root_digest| Snapshot {
      digest: root_digest,
      path_stats: path_stats,
    })
    .to_boxed()
  }

  ///
  /// Given Digest(s) representing Directory instances, merge them recursively into a single
  /// output Directory Digest.
  ///
  /// If a file is present with the same name and contents multiple times, it will appear once.
  /// If a file is present with the same name, but different contents, an error will be returned.
  ///
  pub fn merge_directories(
    store: Store,
    dir_digests: Vec<Digest>,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Digest, String> {
    if dir_digests.is_empty() {
      return future::ok(EMPTY_DIGEST).to_boxed();
    } else if dir_digests.len() == 1 {
      let mut dir_digests = dir_digests;
      return future::ok(dir_digests.pop().unwrap()).to_boxed();
    }

    let directories = dir_digests
      .into_iter()
      .map(|digest| {
        store
          .load_directory(digest, workunit_store.clone())
          .and_then(move |maybe_directory| {
            maybe_directory
              .map(|(dir, _metadata)| dir)
              .ok_or_else(|| format!("Digest {:?} did not exist in the Store.", digest))
          })
      })
      .collect::<Vec<_>>();
    join_all(directories)
      .and_then(move |mut directories| {
        let mut out_dir = bazel_protos::remote_execution::Directory::new();

        // Merge FileNodes.
        let file_nodes = Iterator::flatten(
          directories
            .iter_mut()
            .map(|directory| directory.take_files().into_iter()),
        )
        .sorted_by(|a, b| a.name.cmp(&b.name));

        out_dir.set_files(protobuf::RepeatedField::from_vec(
          file_nodes.into_iter().dedup().collect(),
        ));
        let unique_count = out_dir
          .get_files()
          .iter()
          .map(bazel_protos::remote_execution::FileNode::get_name)
          .dedup()
          .count();
        if unique_count != out_dir.get_files().len() {
          let groups = out_dir
            .get_files()
            .iter()
            .group_by(|f| f.get_name().to_owned());
          for (file_name, group) in &groups {
            if group.count() > 1 {
              return future::err(format!(
                "Can only merge Directories with no duplicates, but found duplicate files: {}",
                file_name
              ))
              .to_boxed();
            }
          }
        }

        // Group and recurse for DirectoryNodes.
        let sorted_child_directories = {
          let mut directories_to_merge = Iterator::flatten(
            directories
              .iter_mut()
              .map(|directory| directory.take_directories().into_iter()),
          )
          .collect::<Vec<_>>();
          directories_to_merge.sort_by(|a, b| a.name.cmp(&b.name));
          directories_to_merge
        };
        let store2 = store.clone();
        let workunit_store2 = workunit_store.clone();
        join_all(
          sorted_child_directories
            .into_iter()
            .group_by(|d| d.name.clone())
            .into_iter()
            .map(move |(child_name, group)| {
              let store2 = store2.clone();
              let workunit_store2 = workunit_store2.clone();
              let digests_result = group
                .map(|d| d.get_digest().into())
                .collect::<Result<Vec<_>, String>>();
              future::done(digests_result)
                .and_then(move |digests| {
                  Self::merge_directories(store2.clone(), digests, workunit_store2.clone())
                })
                .map(move |merged_digest| {
                  let mut child_dir = bazel_protos::remote_execution::DirectoryNode::new();
                  child_dir.set_name(child_name);
                  child_dir.set_digest((&merged_digest).into());
                  child_dir
                })
            })
            .collect::<Vec<_>>(),
        )
        .and_then(move |child_directories| {
          out_dir.set_directories(protobuf::RepeatedField::from_vec(child_directories));
          store.record_directory(&out_dir, true)
        })
        .to_boxed()
      })
      .to_boxed()
  }

  pub fn strip_prefix(
    store: Store,
    root_digest: Digest,
    prefix: PathBuf,
    workunit_store: WorkUnitStore,
  ) -> impl Future<Item = Digest, Error = String> {
    let store2 = store.clone();
    Self::get_directory_or_err(store.clone(), root_digest, workunit_store.clone())
      .and_then(move |dir| {
        futures::future::loop_fn(
          (dir, PathBuf::new(), prefix),
          move |(dir, already_stripped, prefix)| {
            let has_already_stripped_any = already_stripped.components().next().is_some();

            let mut components = prefix.components();
            let component_to_strip = components.next();
            if let Some(component_to_strip) = component_to_strip {
              let remaining_prefix = components.collect();
              let component_to_strip_str = component_to_strip.as_os_str().to_string_lossy();

              let mut saw_matching_dir = false;
              let extra_directories: Vec<_> = dir.get_directories().iter().filter_map(|subdir| {
                if subdir.get_name() == component_to_strip_str {
                  saw_matching_dir = true;
                  None
                } else {
                  Some(subdir.get_name().to_owned())
                }
              }).collect();
              let files: Vec<_> = dir.get_files().iter().map(|file| file.get_name().to_owned()).collect();

              match (saw_matching_dir, extra_directories.is_empty() && files.is_empty()) {
                (false, true) => futures::future::ok(futures::future::Loop::Break(bazel_protos::remote_execution::Directory::new())).to_boxed(),
                (false, false) => {
                  // Prefer "No subdirectory found" error to "had extra files" error.
                  futures::future::err(format!(
                    "Cannot strip prefix {} from root directory {:?} - {}directory{} didn't contain a directory named {}{}",
                    already_stripped.join(&prefix).display(),
                    root_digest,
                    if has_already_stripped_any { "sub" } else { "root " },
                    if has_already_stripped_any { format!(" {}", already_stripped.display()) } else { String::new() },
                    component_to_strip_str,
                    if !extra_directories.is_empty() || !files.is_empty() { format!(" but did contain {}", Self::directories_and_files(&extra_directories, &files)) } else { String::new() },
                  )).to_boxed()
                },
                (true, false) => {
                  futures::future::err(format!(
                    "Cannot strip prefix {} from root directory {:?} - {}directory{} contained non-matching {}",
                    already_stripped.join(&prefix).display(),
                    root_digest,
                    if has_already_stripped_any { "sub" } else { "root " },
                    if has_already_stripped_any { format!(" {}", already_stripped.display()) } else { String::new() },
                    Self::directories_and_files(&extra_directories, &files),
                  )).to_boxed()
                },
                (true, true) => {
                  // Must be 0th index, because we've checked that we saw a matching directory, and no others.
                  let maybe_digest: Result<Digest, String> = dir.get_directories()[0]
                      .get_digest()
                      .into();
                  let next_already_stripped = already_stripped.join(component_to_strip);
                  let dir = Self::get_directory_or_err(store.clone(), try_future!(maybe_digest), workunit_store.clone());
                  dir
                      .map(|dir| {
                        futures::future::Loop::Continue((dir, next_already_stripped, remaining_prefix))
                      })
                      .to_boxed()
                }
              }
            } else {
              futures::future::ok(futures::future::Loop::Break(dir)).to_boxed()
            }
          },
        )
      })
      .and_then(move |dir| store2.record_directory(&dir, true))
  }

  fn directories_and_files(directories: &[String], files: &[String]) -> String {
    format!(
      "{}{}{}",
      if directories.is_empty() {
        String::new()
      } else {
        format!(
          "director{} named: {}",
          if directories.len() == 1 { "y" } else { "ies" },
          directories.join(", ")
        )
      },
      if !directories.is_empty() && !files.is_empty() {
        " and "
      } else {
        ""
      },
      if files.is_empty() {
        String::new()
      } else {
        format!(
          "file{} named: {}",
          if files.len() == 1 { "" } else { "s" },
          files.join(", ")
        )
      },
    )
  }

  fn get_directory_or_err(
    store: Store,
    digest: Digest,
    workunit_store: WorkUnitStore,
  ) -> impl Future<Item = bazel_protos::remote_execution::Directory, Error = String> {
    store
      .load_directory(digest, workunit_store)
      .and_then(move |maybe_dir| {
        maybe_dir
          .map(|(dir, _metadata)| dir)
          .ok_or_else(|| format!("{:?} was not known", digest))
      })
  }

  ///
  /// Capture a Snapshot of a presumed-immutable piece of the filesystem.
  ///
  /// Note that we don't use a Graph here, and don't cache any intermediate steps, we just place
  /// the resultant Snapshot into the store and return it. This is important, because we're reading
  /// things from arbitrary filepaths which we don't want to cache in the graph, as we don't watch
  /// them for changes. Because we're not caching things, we can safely configure the virtual
  /// filesystem to be symlink-oblivious.
  ///
  /// If the `digest_hint` is given, first attempt to load the Snapshot using that Digest, and only
  /// fall back to actually walking the filesystem if we don't have it (either due to garbage
  /// collection or Digest-oblivious legacy caching).
  ///
  pub fn capture_snapshot_from_arbitrary_root<P: AsRef<Path> + Send + 'static>(
    store: Store,
    executor: task_executor::Executor,
    root_path: P,
    path_globs: PathGlobs,
    digest_hint: Option<Digest>,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Snapshot, String> {
    // Attempt to use the digest hint to load a Snapshot without expanding the globs; otherwise,
    // expand the globs to capture a Snapshot.
    let store2 = store.clone();
    let workunit_store2 = workunit_store.clone();
    future::result(digest_hint.ok_or_else(|| "No digest hint provided.".to_string()))
      .and_then(move |digest| Snapshot::from_digest(store, digest, workunit_store))
      .or_else(|_| {
        let posix_fs = Arc::new(try_future!(PosixFS::new_with_symlink_behavior(
          root_path,
          &[],
          executor,
          SymlinkBehavior::Oblivious
        )));

        posix_fs
          .expand(path_globs)
          .map_err(|err| format!("Error expanding globs: {}", err))
          .and_then(|path_stats| {
            Snapshot::from_path_stats(
              store2.clone(),
              &OneOffStoreFileByDigest::new(store2, posix_fs),
              path_stats,
              workunit_store2,
            )
          })
          .to_boxed()
      })
      .to_boxed()
  }
}

impl fmt::Debug for Snapshot {
  fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
    write!(
      f,
      "Snapshot(digest={:?}, entries={})",
      self.digest,
      self.path_stats.len()
    )
  }
}

fn paths_of_child_dir(paths: Vec<PathStat>) -> Vec<PathStat> {
  paths
    .into_iter()
    .filter_map(|s| {
      if s.path().components().count() == 1 {
        return None;
      }
      Some(match s {
        PathStat::File { path, stat } => PathStat::File {
          path: path.iter().skip(1).collect(),
          stat: stat,
        },
        PathStat::Dir { path, stat } => PathStat::Dir {
          path: path.iter().skip(1).collect(),
          stat: stat,
        },
      })
    })
    .collect()
}

fn osstring_as_utf8(path: OsString) -> Result<String, String> {
  path
    .into_string()
    .map_err(|p| format!("{:?}'s file_name is not representable in UTF8", p))
}

// StoreFileByDigest allows a File to be saved to an underlying Store, in such a way that it can be
// looked up by the Digest produced by the store_by_digest method.
// It is a separate trait so that caching implementations can be written which wrap the Store (used
// to store the bytes) and VFS (used to read the files off disk if needed).
pub trait StoreFileByDigest<Error> {
  fn store_by_digest(&self, file: File, workunit_store: WorkUnitStore) -> BoxFuture<Digest, Error>;
}

///
/// A StoreFileByDigest which reads with a PosixFS and writes to a Store, with no caching.
///
#[derive(Clone)]
pub struct OneOffStoreFileByDigest {
  store: Store,
  posix_fs: Arc<PosixFS>,
}

impl OneOffStoreFileByDigest {
  pub fn new(store: Store, posix_fs: Arc<PosixFS>) -> OneOffStoreFileByDigest {
    OneOffStoreFileByDigest { store, posix_fs }
  }
}

impl StoreFileByDigest<String> for OneOffStoreFileByDigest {
  fn store_by_digest(
    &self,
    file: File,
    // TODO PC: is this needed for the remote trait?
    _: WorkUnitStore,
  ) -> BoxFuture<Digest, String> {
    let store = self.store.clone();
    self
      .posix_fs
      .read_file(&file)
      .map_err(move |err| format!("Error reading file {:?}: {:?}", file, err))
      .and_then(move |content| store.store_file_bytes(content.content, true))
      .to_boxed()
  }
}

#[cfg(test)]
mod tests {
  use futures::future::Future;
  use hashing::{Digest, Fingerprint};
  use tempfile;
  use testutil::data::TestDirectory;
  use testutil::make_file;

  use super::{OneOffStoreFileByDigest, Snapshot};
  use crate::Store;
  use fs::{
    Dir, File, GlobExpansionConjunction, GlobMatching, PathGlobs, PathStat, PosixFS,
    StrictGlobMatching,
  };

  use std;
  use std::path::{Path, PathBuf};
  use std::sync::Arc;
  use workunit_store::WorkUnitStore;

  const STR: &str = "European Burmese";

  fn setup() -> (
    Store,
    tempfile::TempDir,
    Arc<PosixFS>,
    OneOffStoreFileByDigest,
    task_executor::Executor,
  ) {
    let executor = task_executor::Executor::new();
    // TODO: Pass a remote CAS address through.
    let store = Store::local_only(
      executor.clone(),
      tempfile::Builder::new()
        .prefix("lmdb_store")
        .tempdir()
        .unwrap(),
    )
    .unwrap();
    let dir = tempfile::Builder::new().prefix("root").tempdir().unwrap();
    let posix_fs = Arc::new(PosixFS::new(dir.path(), &[], task_executor::Executor::new()).unwrap());
    let file_saver = OneOffStoreFileByDigest::new(store.clone(), posix_fs.clone());
    (store, dir, posix_fs, file_saver, executor)
  }

  #[test]
  fn snapshot_one_file() {
    let (store, dir, posix_fs, digester, runtime) = setup();

    let file_name = PathBuf::from("roland");
    make_file(&dir.path().join(&file_name), STR.as_bytes(), 0o600);

    let path_stats = expand_all_sorted(posix_fs, &runtime);
    let snapshot = runtime
      .block_on(Snapshot::from_path_stats(
        store,
        &digester,
        path_stats.clone(),
        WorkUnitStore::new(),
      ))
      .unwrap();
    assert_eq!(
      snapshot,
      Snapshot {
        digest: Digest(
          Fingerprint::from_hex_string(
            "63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16",
          )
          .unwrap(),
          80,
        ),
        path_stats: path_stats,
      }
    );
  }

  #[test]
  fn snapshot_recursive_directories() {
    let (store, dir, posix_fs, digester, runtime) = setup();

    let cats = PathBuf::from("cats");
    let roland = cats.join("roland");
    std::fs::create_dir_all(&dir.path().join(cats)).unwrap();
    make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

    let path_stats = expand_all_sorted(posix_fs, &runtime);
    let snapshot = runtime
      .block_on(Snapshot::from_path_stats(
        store,
        &digester,
        path_stats.clone(),
        WorkUnitStore::new(),
      ))
      .unwrap();
    assert_eq!(
      snapshot,
      Snapshot {
        digest: Digest(
          Fingerprint::from_hex_string(
            "8b1a7ea04eaa2527b35683edac088bc826117b53b7ec6601740b55e20bce3deb",
          )
          .unwrap(),
          78,
        ),
        path_stats: path_stats,
      }
    );
  }

  #[test]
  fn snapshot_from_digest() {
    let (store, dir, posix_fs, digester, runtime) = setup();

    let cats = PathBuf::from("cats");
    let roland = cats.join("roland");
    std::fs::create_dir_all(&dir.path().join(cats)).unwrap();
    make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

    let path_stats = expand_all_sorted(posix_fs, &runtime);
    let expected_snapshot = runtime
      .block_on(Snapshot::from_path_stats(
        store.clone(),
        &digester,
        path_stats.clone(),
        WorkUnitStore::new(),
      ))
      .unwrap();
    assert_eq!(
      expected_snapshot,
      runtime
        .block_on(Snapshot::from_digest(
          store,
          expected_snapshot.digest,
          WorkUnitStore::new()
        ))
        .unwrap()
    );
  }

  #[test]
  fn snapshot_recursive_directories_including_empty() {
    let (store, dir, posix_fs, digester, runtime) = setup();

    let cats = PathBuf::from("cats");
    let roland = cats.join("roland");
    let dogs = PathBuf::from("dogs");
    let llamas = PathBuf::from("llamas");
    std::fs::create_dir_all(&dir.path().join(&cats)).unwrap();
    std::fs::create_dir_all(&dir.path().join(&dogs)).unwrap();
    std::fs::create_dir_all(&dir.path().join(&llamas)).unwrap();
    make_file(&dir.path().join(&roland), STR.as_bytes(), 0o600);

    let sorted_path_stats = expand_all_sorted(posix_fs, &runtime);
    let mut unsorted_path_stats = sorted_path_stats.clone();
    unsorted_path_stats.reverse();
    assert_eq!(
      runtime
        .block_on(Snapshot::from_path_stats(
          store,
          &digester,
          unsorted_path_stats.clone(),
          WorkUnitStore::new(),
        ))
        .unwrap(),
      Snapshot {
        digest: Digest(
          Fingerprint::from_hex_string(
            "fbff703bdaac62accf2ea5083bcfed89292073bf710ef9ad14d9298c637e777b",
          )
          .unwrap(),
          232,
        ),
        path_stats: sorted_path_stats,
      }
    );
  }

  #[test]
  fn merge_directories_two_files() {
    let (store, _, _, _, runtime) = setup();

    let containing_roland = TestDirectory::containing_roland();
    let containing_treats = TestDirectory::containing_treats();

    runtime
      .block_on(store.record_directory(&containing_roland.directory(), false))
      .expect("Storing roland directory");
    runtime
      .block_on(store.record_directory(&containing_treats.directory(), false))
      .expect("Storing treats directory");

    let result = runtime.block_on(Snapshot::merge_directories(
      store,
      vec![containing_treats.digest(), containing_roland.digest()],
      WorkUnitStore::new(),
    ));

    assert_eq!(
      result,
      Ok(TestDirectory::containing_roland_and_treats().digest())
    );
  }

  #[test]
  fn merge_directories_clashing_files() {
    let (store, _, _, _, runtime) = setup();

    let containing_roland = TestDirectory::containing_roland();
    let containing_wrong_roland = TestDirectory::containing_wrong_roland();

    runtime
      .block_on(store.record_directory(&containing_roland.directory(), false))
      .expect("Storing roland directory");
    runtime
      .block_on(store.record_directory(&containing_wrong_roland.directory(), false))
      .expect("Storing wrong roland directory");

    let err = runtime
      .block_on(Snapshot::merge_directories(
        store,
        vec![containing_roland.digest(), containing_wrong_roland.digest()],
        WorkUnitStore::new(),
      ))
      .expect_err("Want error merging");

    assert!(
      err.contains("roland"),
      "Want error message to contain roland but was: {}",
      err
    );
  }

  #[test]
  fn merge_directories_same_files() {
    let (store, _, _, _, runtime) = setup();

    let containing_roland = TestDirectory::containing_roland();
    let containing_roland_and_treats = TestDirectory::containing_roland_and_treats();

    runtime
      .block_on(store.record_directory(&containing_roland.directory(), false))
      .expect("Storing roland directory");
    runtime
      .block_on(store.record_directory(&containing_roland_and_treats.directory(), false))
      .expect("Storing treats directory");

    let result = runtime.block_on(Snapshot::merge_directories(
      store,
      vec![
        containing_roland.digest(),
        containing_roland_and_treats.digest(),
      ],
      WorkUnitStore::new(),
    ));

    assert_eq!(
      result,
      Ok(TestDirectory::containing_roland_and_treats().digest())
    );
  }

  #[test]
  fn snapshot_merge_two_files() {
    let (store, tempdir, _, digester, runtime) = setup();

    let common_dir_name = "tower";
    let common_dir = PathBuf::from(common_dir_name);

    let dir = make_dir_stat(tempdir.path(), &common_dir);
    let file1 = make_file_stat(
      tempdir.path(),
      &common_dir.join("roland"),
      STR.as_bytes(),
      false,
    );
    let file2 = make_file_stat(
      tempdir.path(),
      &common_dir.join("susannah"),
      STR.as_bytes(),
      true,
    );

    let snapshot1 = runtime
      .block_on(Snapshot::from_path_stats(
        store.clone(),
        &digester,
        vec![dir.clone(), file1.clone()],
        WorkUnitStore::new(),
      ))
      .unwrap();

    let snapshot2 = runtime
      .block_on(Snapshot::from_path_stats(
        store.clone(),
        &digester,
        vec![dir.clone(), file2.clone()],
        WorkUnitStore::new(),
      ))
      .unwrap();

    let merged = runtime
      .block_on(Snapshot::merge(
        store.clone(),
        &[snapshot1, snapshot2],
        WorkUnitStore::new(),
      ))
      .unwrap();
    let merged_root_directory = runtime
      .block_on(store.load_directory(merged.digest, WorkUnitStore::new()))
      .unwrap()
      .unwrap()
      .0;

    assert_eq!(merged.path_stats, vec![dir, file1, file2]);
    assert_eq!(merged_root_directory.files.len(), 0);
    assert_eq!(merged_root_directory.directories.len(), 1);

    let merged_child_dirnode = merged_root_directory.directories[0].clone();
    let merged_child_dirnode_digest: Result<Digest, String> =
      merged_child_dirnode.get_digest().into();
    let merged_child_directory = runtime
      .block_on(store.load_directory(merged_child_dirnode_digest.unwrap(), WorkUnitStore::new()))
      .unwrap()
      .unwrap()
      .0;

    assert_eq!(merged_child_dirnode.name, common_dir_name);
    assert_eq!(
      merged_child_directory
        .files
        .iter()
        .map(|filenode| filenode.name.clone())
        .collect::<Vec<_>>(),
      vec!["roland".to_string(), "susannah".to_string()],
    );
  }

  #[test]
  fn snapshot_merge_colliding() {
    let (store, tempdir, _, digester, runtime) = setup();

    let file = make_file_stat(
      tempdir.path(),
      &PathBuf::from("roland"),
      STR.as_bytes(),
      false,
    );

    let snapshot1 = runtime
      .block_on(Snapshot::from_path_stats(
        store.clone(),
        &digester,
        vec![file.clone()],
        WorkUnitStore::new(),
      ))
      .unwrap();

    let snapshot2 = runtime
      .block_on(Snapshot::from_path_stats(
        store.clone(),
        &digester,
        vec![file],
        WorkUnitStore::new(),
      ))
      .unwrap();

    let merged_res =
      Snapshot::merge(store.clone(), &[snapshot1, snapshot2], WorkUnitStore::new()).wait();

    match merged_res {
      Err(ref msg) if msg.contains("contained duplicate path") && msg.contains("roland") => (),
      x => panic!(
        "Snapshot::merge should have failed with a useful message; got: {:?}",
        x
      ),
    }
  }

  #[test]
  fn strip_empty_prefix() {
    let (store, _, _, _, runtime) = setup();

    let dir = TestDirectory::nested();
    runtime
      .block_on(store.record_directory(&dir.directory(), false))
      .expect("Error storing directory");

    let result = runtime.block_on(super::Snapshot::strip_prefix(
      store,
      dir.digest(),
      PathBuf::from(""),
      WorkUnitStore::new(),
    ));
    assert_eq!(result, Ok(dir.digest()));
  }

  #[test]
  fn strip_non_empty_prefix() {
    let (store, _, _, _, runtime) = setup();

    let dir = TestDirectory::nested();
    runtime
      .block_on(store.record_directory(&dir.directory(), false))
      .expect("Error storing directory");
    runtime
      .block_on(store.record_directory(&TestDirectory::containing_roland().directory(), false))
      .expect("Error storing directory");

    let result = runtime.block_on(super::Snapshot::strip_prefix(
      store,
      dir.digest(),
      PathBuf::from("cats"),
      WorkUnitStore::new(),
    ));
    assert_eq!(result, Ok(TestDirectory::containing_roland().digest()));
  }

  #[test]
  fn strip_prefix_empty_subdir() {
    let (store, _, _, _, runtime) = setup();

    let dir = TestDirectory::containing_falcons_dir();
    runtime
      .block_on(store.record_directory(&dir.directory(), false))
      .expect("Error storing directory");

    let result = runtime.block_on(super::Snapshot::strip_prefix(
      store,
      dir.digest(),
      PathBuf::from("falcons/peregrine"),
      WorkUnitStore::new(),
    ));
    assert_eq!(result, Ok(TestDirectory::empty().digest()));
  }

  #[test]
  fn strip_dir_not_in_store() {
    let (store, _, _, _, runtime) = setup();
    let digest = TestDirectory::nested().digest();
    let result = runtime.block_on(super::Snapshot::strip_prefix(
      store,
      digest,
      PathBuf::from("cats"),
      WorkUnitStore::new(),
    ));
    assert_eq!(result, Err(format!("{:?} was not known", digest)));
  }

  #[test]
  fn strip_subdir_not_in_store() {
    let (store, _, _, _, runtime) = setup();
    let dir = TestDirectory::nested();
    runtime
      .block_on(store.record_directory(&dir.directory(), false))
      .expect("Error storing directory");
    let result = runtime.block_on(super::Snapshot::strip_prefix(
      store,
      dir.digest(),
      PathBuf::from("cats"),
      WorkUnitStore::new(),
    ));
    assert_eq!(
      result,
      Err(format!(
        "{:?} was not known",
        TestDirectory::containing_roland().digest()
      ))
    );
  }

  #[test]
  fn strip_prefix_non_matching_file() {
    let (store, _, _, _, runtime) = setup();
    let dir = TestDirectory::recursive();
    let child_dir = TestDirectory::containing_roland();
    runtime
      .block_on(store.record_directory(&dir.directory(), false))
      .expect("Error storing directory");
    runtime
      .block_on(store.record_directory(&child_dir.directory(), false))
      .expect("Error storing directory");
    let result = runtime.block_on(super::Snapshot::strip_prefix(
      store,
      dir.digest(),
      PathBuf::from("cats"),
      WorkUnitStore::new(),
    ));

    assert_eq!(result, Err(format!("Cannot strip prefix cats from root directory {:?} - root directory contained non-matching file named: treats", dir.digest())));
  }

  #[test]
  fn strip_prefix_non_matching_dir() {
    let (store, _, _, _, runtime) = setup();
    let dir = TestDirectory::double_nested_dir_and_file();
    let child_dir = TestDirectory::nested_dir_and_file();
    runtime
      .block_on(store.record_directory(&dir.directory(), false))
      .expect("Error storing directory");
    runtime
      .block_on(store.record_directory(&child_dir.directory(), false))
      .expect("Error storing directory");
    let result = runtime.block_on(super::Snapshot::strip_prefix(
      store,
      dir.digest(),
      PathBuf::from("animals/cats"),
      WorkUnitStore::new(),
    ));

    assert_eq!(result, Err(format!("Cannot strip prefix animals/cats from root directory {:?} - subdirectory animals contained non-matching directory named: birds", dir.digest())));
  }

  #[test]
  fn strip_subdir_not_in_dir() {
    let (store, _, _, _, runtime) = setup();
    let dir = TestDirectory::nested();
    runtime
      .block_on(store.record_directory(&dir.directory(), false))
      .expect("Error storing directory");
    runtime
      .block_on(store.record_directory(&TestDirectory::containing_roland().directory(), false))
      .expect("Error storing directory");
    let result = runtime.block_on(super::Snapshot::strip_prefix(
      store,
      dir.digest(),
      PathBuf::from("cats/ugly"),
      WorkUnitStore::new(),
    ));
    assert_eq!(result, Err(format!("Cannot strip prefix cats/ugly from root directory {:?} - subdirectory cats didn't contain a directory named ugly but did contain file named: roland", dir.digest())));
  }

  fn make_dir_stat(root: &Path, relpath: &Path) -> PathStat {
    std::fs::create_dir(root.join(relpath)).unwrap();
    PathStat::dir(relpath.to_owned(), Dir(relpath.to_owned()))
  }

  fn make_file_stat(root: &Path, relpath: &Path, contents: &[u8], is_executable: bool) -> PathStat {
    make_file(
      &root.join(relpath),
      contents,
      if is_executable { 0o555 } else { 0o444 },
    );
    PathStat::file(
      relpath.to_owned(),
      File {
        path: relpath.to_owned(),
        is_executable,
      },
    )
  }

  fn expand_all_sorted(
    posix_fs: Arc<PosixFS>,
    executor: &task_executor::Executor,
  ) -> Vec<PathStat> {
    let mut v = executor
      .block_on(
        posix_fs.expand(
          // Don't error or warn if there are no paths matched -- that is a valid state.
          PathGlobs::create(
            &["**".to_owned()],
            &[],
            StrictGlobMatching::Ignore,
            GlobExpansionConjunction::AllMatch,
          )
          .unwrap(),
        ),
      )
      .unwrap();
    v.sort_by(|a, b| a.path().cmp(b.path()));
    v
  }
}
