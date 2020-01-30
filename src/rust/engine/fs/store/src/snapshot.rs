// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use crate::Store;
use bazel_protos;
use boxfuture::{try_future, BoxFuture, Boxable};
use fs::{Dir, File, GlobMatching, PathGlobs, PathStat, PosixFS, SymlinkBehavior};
use futures01::future::{self, join_all};
use futures01::Future;
use hashing::{Digest, EMPTY_DIGEST};
use indexmap::{self, IndexMap};
use itertools::Itertools;
use protobuf;
use std::collections::BTreeSet;
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
                .and_then(move |digests| Self::merge_directories(store2, digests, workunit_store2))
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

  pub fn add_prefix(
    store: Store,
    digest: Digest,
    prefix: PathBuf,
  ) -> impl Future<Item = Digest, Error = String> {
    let mut dir_node = bazel_protos::remote_execution::DirectoryNode::new();
    dir_node.set_name(try_future!(osstring_as_utf8(prefix.into_os_string())));
    dir_node.set_digest((&digest).into());

    let mut out_dir = bazel_protos::remote_execution::Directory::new();
    out_dir.set_directories(protobuf::RepeatedField::from_vec(vec![dir_node]));

    store.record_directory(&out_dir, true)
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
        future::loop_fn(
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
                (false, true) => future::ok(future::Loop::Break(bazel_protos::remote_execution::Directory::new())).to_boxed(),
                (false, false) => {
                  // Prefer "No subdirectory found" error to "had extra files" error.
                  future::err(format!(
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
                  future::err(format!(
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
                        future::Loop::Continue((dir, next_already_stripped, remaining_prefix))
                      })
                      .to_boxed()
                }
              }
            } else {
              future::ok(future::Loop::Break(dir)).to_boxed()
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

  pub fn get_snapshot_subset(
    store: Store,
    digest: Digest,
    include_files: BTreeSet<String>,
    include_dirs: BTreeSet<String>,
    workunit_store: WorkUnitStore,
  ) -> BoxFuture<Digest, String> {
    use bazel_protos::remote_execution::{Directory, DirectoryNode, FileNode};
    use protobuf::RepeatedField;

    let directory = store
      .load_directory(digest, workunit_store)
      .and_then(move |maybe_directory| {
        maybe_directory
          .map(|(dir, _metadata)| dir)
          .ok_or_else(|| format!("Digest {:?} did not exist in the Store.", digest))
      });
    directory
      .and_then(move |mut directory: Directory| {
        let mut out_dir = Directory::new();
        let file_nodes: RepeatedField<FileNode> = directory.take_files();
        let subset_file_nodes = file_nodes
          .into_iter()
          .filter(|orig_file: &FileNode| include_files.contains(orig_file.get_name()))
          .collect();
        out_dir.set_files(subset_file_nodes);

        let directory_nodes: RepeatedField<DirectoryNode> = directory.take_directories();
        let subset_dir_nodes = directory_nodes
          .into_iter()
          .filter(|orig_dir: &DirectoryNode| include_dirs.contains(orig_dir.get_name()))
          .collect();

        out_dir.set_directories(subset_dir_nodes);
        store.record_directory(&out_dir, true)
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
