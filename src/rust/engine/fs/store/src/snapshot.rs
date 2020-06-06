// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::{HashMap, HashSet};
use std::convert::TryInto;
use std::ffi::OsString;
use std::fmt;
use std::iter::Iterator;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use crate::Store;
use boxfuture::{BoxFuture, Boxable};
use bytes::Bytes;
use fs::{
  Dir, File, GitignoreStyleExcludes, GlobMatching, PathStat, PosixFS, PreparedPathGlobs,
  SymlinkBehavior,
};
use futures::compat::Future01CompatExt;
use futures::future::{self as future03, FutureExt, TryFutureExt};
use futures01::future;
use hashing::{Digest, EMPTY_DIGEST};
use indexmap::{self, IndexMap};
use itertools::Itertools;

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

  pub async fn from_path_stats<
    S: StoreFileByDigest<Error> + Sized + Clone + Send + 'static,
    Error: fmt::Debug + 'static + Send,
  >(
    store: Store,
    file_digester: S,
    mut path_stats: Vec<PathStat>,
  ) -> Result<Snapshot, String> {
    path_stats.sort_by(|a, b| a.path().cmp(b.path()));

    // The helper assumes that if a Path has multiple children, it must be a directory.
    // Proactively error if we run into identically named files, because otherwise we will treat
    // them like empty directories.
    let pre_dedupe_len = path_stats.len();
    path_stats.dedup_by(|a, b| a.path() == b.path());
    if path_stats.len() != pre_dedupe_len {
      return Err(format!(
        "Snapshots must be constructed from unique path stats; got duplicates in {:?}",
        path_stats
      ));
    }
    let digest =
      Snapshot::ingest_directory_from_sorted_path_stats(store, file_digester, &path_stats).await?;

    Ok(Snapshot { digest, path_stats })
  }

  pub async fn from_digest(store: Store, digest: Digest) -> Result<Snapshot, String> {
    let path_stats_per_directory = store
      .walk(digest, |_, path_so_far, _, directory| {
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
      })
      .compat()
      .await?;

    let mut path_stats =
      Iterator::flatten(path_stats_per_directory.into_iter().map(Vec::into_iter))
        .collect::<Vec<_>>();
    path_stats.sort_by(|l, r| l.path().cmp(&r.path()));
    Ok(Snapshot { digest, path_stats })
  }

  pub async fn digest_from_path_stats<
    S: StoreFileByDigest<Error> + Sized + Clone + Send + 'static,
    Error: fmt::Debug + 'static + Send,
  >(
    store: Store,
    file_digester: S,
    path_stats: &[PathStat],
  ) -> Result<Digest, String> {
    let mut sorted_path_stats = path_stats.to_owned();
    sorted_path_stats.sort_by(|a, b| a.path().cmp(b.path()));
    Snapshot::ingest_directory_from_sorted_path_stats(store, file_digester, &sorted_path_stats)
      .await
  }

  // NB: This function is recursive, and so cannot be directly marked async:
  //   https://rust-lang.github.io/async-book/07_workarounds/05_recursion.html
  fn ingest_directory_from_sorted_path_stats<
    S: StoreFileByDigest<Error> + Sized + Clone + Send + 'static,
    Error: fmt::Debug + 'static + Send,
  >(
    store: Store,
    file_digester: S,
    path_stats: &[PathStat],
  ) -> future03::BoxFuture<Result<Digest, String>> {
    let mut file_futures = Vec::new();
    let mut dir_futures: Vec<
      future03::BoxFuture<Result<bazel_protos::remote_execution::DirectoryNode, String>>,
    > = Vec::new();

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
            let stat = stat.clone();
            let file_digester = file_digester.clone();
            file_futures.push(async move {
              let digest_future = file_digester.store_by_digest(stat);
              let digest = digest_future
                .compat()
                .await
                .map_err(|e| format!("{:?}", e))?;

              let mut file_node = bazel_protos::remote_execution::FileNode::new();
              file_node.set_name(osstring_as_utf8(first_component)?);
              file_node.set_digest((&digest).into());
              file_node.set_is_executable(is_executable);
              Ok(file_node)
            });
          }
          PathStat::Dir { .. } => {
            let store = store.clone();
            // Because there are no children of this Dir, it must be empty.
            dir_futures.push(Box::pin(async move {
              let digest = store
                .record_directory(&bazel_protos::remote_execution::Directory::new(), true)
                .await?;
              let mut directory_node = bazel_protos::remote_execution::DirectoryNode::new();
              directory_node.set_name(osstring_as_utf8(first_component).unwrap());
              directory_node.set_digest((&digest).into());
              Ok(directory_node)
            }));
          }
        }
      } else {
        let store = store.clone();
        let file_digester = file_digester.clone();
        dir_futures.push(Box::pin(async move {
          // TODO: Memoize this in the graph
          let digest = Snapshot::ingest_directory_from_sorted_path_stats(
            store,
            file_digester,
            &paths_of_child_dir(path_group),
          )
          .await?;

          let mut dir_node = bazel_protos::remote_execution::DirectoryNode::new();
          dir_node.set_name(osstring_as_utf8(first_component)?);
          dir_node.set_digest((&digest).into());
          Ok(dir_node)
        }));
      }
    }

    async move {
      let (dirs, files) = future03::try_join(
        future03::try_join_all(dir_futures),
        future03::try_join_all(file_futures),
      )
      .await?;

      let mut directory = bazel_protos::remote_execution::Directory::new();
      directory.set_directories(protobuf::RepeatedField::from_vec(dirs));
      directory.set_files(protobuf::RepeatedField::from_vec(files));
      store.record_directory(&directory, true).await
    }
    .boxed()
  }

  ///
  /// Given N Snapshots, returns a new Snapshot that merges them.
  ///
  /// Any files that exist in multiple Snapshots will cause this method to fail: the assumption
  /// behind this behaviour is that almost any colliding file would represent a Rule implementation
  /// error, and in cases where overwriting a file is desirable, explicitly removing a duplicated
  /// copy should be straightforward.
  ///
  pub async fn merge(store: Store, snapshots: &[Snapshot]) -> Result<Snapshot, String> {
    // We dedupe PathStats by their symbolic names, as those will be their names within the
    // `Directory` structure. Only `Dir+Dir` collisions are legal.
    let path_stats = {
      let mut uniq_paths: IndexMap<PathBuf, PathStat> = IndexMap::new();
      for path_stat in Iterator::flatten(snapshots.iter().map(|s| s.path_stats.iter().cloned())) {
        match uniq_paths.entry(path_stat.path().to_owned()) {
          indexmap::map::Entry::Occupied(e) => match (&path_stat, e.get()) {
            (&PathStat::Dir { .. }, &PathStat::Dir { .. }) => (),
            (x, y) => {
              return Err(format!(
                "Snapshots contained duplicate path: {:?} vs {:?}",
                x, y
              ));
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
    let root_digest =
      Self::merge_directories(store, snapshots.iter().map(|s| s.digest).collect()).await?;
    Ok(Snapshot {
      digest: root_digest,
      path_stats,
    })
  }

  ///
  /// Given Digest(s) representing Directory instances, merge them recursively into a single
  /// output Directory Digest.
  ///
  /// If a file is present with the same name and contents multiple times, it will appear once.
  /// If a file is present with the same name, but different contents, an error will be returned.
  ///
  pub async fn merge_directories(store: Store, dir_digests: Vec<Digest>) -> Result<Digest, String> {
    Self::merge_directories_recursive(store, PathBuf::new(), dir_digests).await
  }

  // NB: This function is recursive, and so cannot be directly marked async:
  //   https://rust-lang.github.io/async-book/07_workarounds/05_recursion.html
  fn merge_directories_recursive(
    store: Store,
    parent_path: PathBuf,
    dir_digests: Vec<Digest>,
  ) -> future03::BoxFuture<'static, Result<Digest, String>> {
    async move {
      if dir_digests.is_empty() {
        return Ok(EMPTY_DIGEST);
      } else if dir_digests.len() == 1 {
        let mut dir_digests = dir_digests;
        return Ok(dir_digests.pop().unwrap());
      }

      let mut directories = future03::try_join_all(
        dir_digests
          .into_iter()
          .map(|digest| {
            store
              .load_directory(digest)
              .and_then(move |maybe_directory| {
                future03::ready(
                  maybe_directory
                    .map(|(dir, _metadata)| dir)
                    .ok_or_else(|| format!("Digest {:?} did not exist in the Store.", digest)),
                )
              })
          })
          .collect::<Vec<_>>(),
      )
      .await?;

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

      // Group and recurse for DirectoryNodes.
      let child_directory_futures = {
        let store = store.clone();
        let parent_path = parent_path.clone();
        let mut directories_to_merge = Iterator::flatten(
          directories
            .iter_mut()
            .map(|directory| directory.take_directories().into_iter()),
        )
        .collect::<Vec<_>>();
        directories_to_merge.sort_by(|a, b| a.name.cmp(&b.name));
        directories_to_merge
          .into_iter()
          .group_by(|d| d.name.clone())
          .into_iter()
          .map(move |(child_name, group)| {
            let store = store.clone();
            let digests_result = group
              .map(|d| d.get_digest().try_into())
              .collect::<Result<Vec<_>, String>>();
            let child_path = parent_path.join(&child_name);
            async move {
              let digests = digests_result?;
              let merged_digest =
                Self::merge_directories_recursive(store, child_path, digests).await?;
              let mut child_dir = bazel_protos::remote_execution::DirectoryNode::new();
              child_dir.set_name(child_name);
              child_dir.set_digest((&merged_digest).into());
              let res: Result<_, String> = Ok(child_dir);
              res
            }
          })
          .collect::<Vec<_>>()
      };

      let child_directories = future03::try_join_all(child_directory_futures).await?;

      out_dir.set_directories(protobuf::RepeatedField::from_vec(child_directories));

      Self::error_for_collisions(&store, &parent_path, &out_dir).await?;
      store.record_directory(&out_dir, true).await
    }
    .boxed()
  }

  ///
  /// Ensure merge is unique and fail with debugging info if not.
  ///
  async fn error_for_collisions(
    store: &Store,
    parent_path: &Path,
    dir: &bazel_protos::remote_execution::Directory,
  ) -> Result<(), String> {
    // Attempt to cheaply check for collisions to bail out early if there aren't any.
    let unique_count = dir
      .get_files()
      .iter()
      .map(bazel_protos::remote_execution::FileNode::get_name)
      .chain(
        dir
          .get_directories()
          .iter()
          .map(bazel_protos::remote_execution::DirectoryNode::get_name),
      )
      .collect::<HashSet<_>>()
      .len();
    if unique_count == (dir.get_files().len() + dir.get_directories().len()) {
      return Ok(());
    }

    let file_details_by_name = dir
      .get_files()
      .iter()
      .map(|file_node| async move {
        let digest_proto = file_node.get_digest();
        let header = format!(
          "file digest={} size={}:\n\n",
          digest_proto.hash, digest_proto.size_bytes
        );

        let digest_res: Result<hashing::Digest, String> = digest_proto.try_into();
        let contents = store
          .load_file_bytes_with(digest_res?, |bytes| {
            const MAX_LENGTH: usize = 1024;
            let content_length = bytes.len();
            let mut bytes = Bytes::from(&bytes[0..std::cmp::min(content_length, MAX_LENGTH)]);
            if content_length > MAX_LENGTH && !log_enabled!(log::Level::Debug) {
              bytes.extend_from_slice(
                format!(
                  "\n... TRUNCATED contents from {}B to {}B \
                  (Pass -ldebug to see full contents).",
                  content_length, MAX_LENGTH
                )
                .as_bytes(),
              );
            }
            String::from_utf8_lossy(bytes.to_vec().as_slice()).to_string()
          })
          .await?
          .map(|(content, _metadata)| content)
          .unwrap_or_else(|| "<could not load contents>".to_string());
        let detail = format!("{}{}", header, contents);
        let res: Result<_, String> = Ok((file_node.get_name(), detail));
        res
      })
      .map(|f| f.boxed());
    let dir_details_by_name = dir
      .get_directories()
      .iter()
      .map(|dir_node| async move {
        let digest_proto = dir_node.get_digest();
        let detail = format!(
          "dir digest={} size={}:\n\n",
          digest_proto.hash, digest_proto.size_bytes
        );
        let res: Result<_, String> = Ok((dir_node.get_name(), detail));
        res
      })
      .map(|f| f.boxed());

    let duplicate_details = async move {
      let details_by_name = future03::try_join_all(
        file_details_by_name
          .chain(dir_details_by_name)
          .collect::<Vec<_>>(),
      )
      .await?
      .into_iter()
      .into_group_map();

      let enumerated_details =
        std::iter::Iterator::flatten(details_by_name.iter().filter_map(|(name, details)| {
          if details.len() > 1 {
            Some(
              details
                .iter()
                .enumerate()
                .map(move |(index, detail)| format!("`{}`: {}.) {}", name, index + 1, detail)),
            )
          } else {
            None
          }
        }))
        .collect();

      let res: Result<Vec<String>, String> = Ok(enumerated_details);
      res
    }
    .await
    .unwrap_or_else(|err| vec![format!("Failed to load contents for comparison: {}", err)]);

    Err(format!(
      "Can only merge Directories with no duplicates, but found {} duplicate entries in {}:\
      \n\n{}",
      duplicate_details.len(),
      parent_path.display(),
      duplicate_details.join("\n\n")
    ))
  }

  pub async fn add_prefix(store: Store, digest: Digest, prefix: PathBuf) -> Result<Digest, String> {
    let mut dir_node = bazel_protos::remote_execution::DirectoryNode::new();
    dir_node.set_name(osstring_as_utf8(prefix.into_os_string())?);
    dir_node.set_digest((&digest).into());

    let mut out_dir = bazel_protos::remote_execution::Directory::new();
    out_dir.set_directories(protobuf::RepeatedField::from_vec(vec![dir_node]));

    store.record_directory(&out_dir, true).await
  }

  pub async fn strip_prefix(
    store: Store,
    root_digest: Digest,
    prefix: PathBuf,
  ) -> Result<Digest, String> {
    let store2 = store.clone();
    let mut dir = Self::get_directory_or_err(store.clone(), root_digest).await?;
    let mut already_stripped = PathBuf::new();
    let mut prefix = prefix;
    loop {
      let has_already_stripped_any = already_stripped.components().next().is_some();

      let mut components = prefix.components();
      let component_to_strip = components.next();
      if let Some(component_to_strip) = component_to_strip {
        let remaining_prefix = components.collect();
        let component_to_strip_str = component_to_strip.as_os_str().to_string_lossy();

        let mut saw_matching_dir = false;
        let extra_directories: Vec<_> = dir
          .get_directories()
          .iter()
          .filter_map(|subdir| {
            if subdir.get_name() == component_to_strip_str {
              saw_matching_dir = true;
              None
            } else {
              Some(subdir.get_name().to_owned())
            }
          })
          .collect();
        let files: Vec<_> = dir
          .get_files()
          .iter()
          .map(|file| file.get_name().to_owned())
          .collect();

        match (saw_matching_dir, extra_directories.is_empty() && files.is_empty()) {
          (false, true) => {
            dir = bazel_protos::remote_execution::Directory::new();
            break;
          },
          (false, false) => {
            // Prefer "No subdirectory found" error to "had extra files" error.
            return Err(format!(
              "Cannot strip prefix {} from root directory {:?} - {}directory{} didn't contain a directory named {}{}",
              already_stripped.join(&prefix).display(),
              root_digest,
              if has_already_stripped_any { "sub" } else { "root " },
              if has_already_stripped_any { format!(" {}", already_stripped.display()) } else { String::new() },
              component_to_strip_str,
              if !extra_directories.is_empty() || !files.is_empty() { format!(" but did contain {}", Self::directories_and_files(&extra_directories, &files)) } else { String::new() },
            ))
          },
          (true, false) => {
            return Err(format!(
              "Cannot strip prefix {} from root directory {:?} - {}directory{} contained non-matching {}",
              already_stripped.join(&prefix).display(),
              root_digest,
              if has_already_stripped_any { "sub" } else { "root " },
              if has_already_stripped_any { format!(" {}", already_stripped.display()) } else { String::new() },
              Self::directories_and_files(&extra_directories, &files),
            ))
          },
          (true, true) => {
            // Must be 0th index, because we've checked that we saw a matching directory, and no others.
            let maybe_digest: Result<Digest, String> = dir.get_directories()[0]
                .get_digest()
                .try_into();
            already_stripped = already_stripped.join(component_to_strip);
            dir = Self::get_directory_or_err(store.clone(), maybe_digest?).await?;
            prefix = remaining_prefix;
          }
        }
      } else {
        break;
      }
    }

    store2.record_directory(&dir, true).await
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

  async fn get_directory_or_err(
    store: Store,
    digest: Digest,
  ) -> Result<bazel_protos::remote_execution::Directory, String> {
    let maybe_dir = store.load_directory(digest).await?;
    maybe_dir
      .map(|(dir, _metadata)| dir)
      .ok_or_else(|| format!("{:?} was not known", digest))
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
  pub async fn capture_snapshot_from_arbitrary_root<P: AsRef<Path> + Send + 'static>(
    store: Store,
    executor: task_executor::Executor,
    root_path: P,
    path_globs: PreparedPathGlobs,
    digest_hint: Option<Digest>,
  ) -> Result<Snapshot, String> {
    // Attempt to use the digest hint to load a Snapshot without expanding the globs; otherwise,
    // expand the globs to capture a Snapshot.
    let snapshot_result = if let Some(digest) = digest_hint {
      Snapshot::from_digest(store.clone(), digest).await
    } else {
      Err("No digest hint provided.".to_string())
    };

    if let Ok(snapshot) = snapshot_result {
      Ok(snapshot)
    } else {
      let posix_fs = Arc::new(PosixFS::new_with_symlink_behavior(
        root_path,
        GitignoreStyleExcludes::create(vec![])?,
        executor,
        SymlinkBehavior::Oblivious,
      )?);

      let path_stats = posix_fs
        .expand(path_globs)
        .await
        .map_err(|err| format!("Error expanding globs: {}", err))?;
      Snapshot::from_path_stats(
        store.clone(),
        OneOffStoreFileByDigest::new(store, posix_fs),
        path_stats,
      )
      .await
    }
  }

  pub async fn get_snapshot_subset(
    store: Store,
    digest: Digest,
    path_globs: PreparedPathGlobs,
  ) -> Result<Snapshot, String> {
    use bazel_protos::remote_execution::{Directory, DirectoryNode, FileNode};

    let traverser = move |_: &Store,
                          path_so_far: &PathBuf,
                          _: Digest,
                          directory: &Directory|
          -> BoxFuture<(Vec<PathStat>, StoreManyFileDigests), String> {
      let subdir_paths: Vec<PathBuf> = directory
        .get_directories()
        .iter()
        .map(move |node: &DirectoryNode| path_so_far.join(node.get_name()))
        .filter(|path: &PathBuf| path_globs.matches(path))
        .collect();

      let file_paths: Vec<(PathBuf, Result<Digest, String>, bool)> = directory
        .get_files()
        .iter()
        .map(|node: &FileNode| {
          (
            path_so_far.join(node.get_name()),
            node.get_digest().try_into(),
            node.is_executable,
          )
        })
        .filter(|(path, _, _)| path_globs.matches(path))
        .collect();

      let mut path_stats: Vec<PathStat> = vec![];
      for path in subdir_paths.into_iter() {
        path_stats.push(PathStat::dir(path.clone(), Dir(path)));
      }

      let mut hash = HashMap::new();
      for (path, maybe_digest, is_executable) in file_paths.into_iter() {
        let digest = match maybe_digest {
          Ok(d) => d,
          Err(err) => return future::err(err).to_boxed(),
        };
        hash.insert(path.clone(), digest);
        path_stats.push(PathStat::file(
          path.clone(),
          File {
            path,
            is_executable,
          },
        ));
      }

      future::ok((path_stats, StoreManyFileDigests { hash })).to_boxed()
    };

    let path_stats_and_stores_per_directory: Vec<(Vec<PathStat>, StoreManyFileDigests)> =
      store.walk(digest, traverser).compat().await?;

    let mut final_store = StoreManyFileDigests::new();
    let mut path_stats: Vec<PathStat> = vec![];
    for (per_dir_path_stats, per_dir_store) in path_stats_and_stores_per_directory.into_iter() {
      final_store.merge(per_dir_store);
      path_stats.extend(per_dir_path_stats.into_iter());
    }

    path_stats.sort_by(|l, r| l.path().cmp(&r.path()));
    Snapshot::from_path_stats(store, final_store, path_stats).await
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
          stat,
        },
        PathStat::Dir { path, stat } => PathStat::Dir {
          path: path.iter().skip(1).collect(),
          stat,
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
  fn store_by_digest(&self, file: File) -> BoxFuture<Digest, Error>;
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
  fn store_by_digest(&self, file: File) -> BoxFuture<Digest, String> {
    let store = self.store.clone();
    let posix_fs = self.posix_fs.clone();
    let res = async move {
      let content = posix_fs
        .read_file(&file)
        .await
        .map_err(move |err| format!("Error reading file {:?}: {:?}", file, err))?;
      store.store_file_bytes(content.content, true).await
    };
    res.boxed().compat().to_boxed()
  }
}

#[derive(Clone)]
struct StoreManyFileDigests {
  pub hash: HashMap<PathBuf, Digest>,
}

impl StoreManyFileDigests {
  fn new() -> StoreManyFileDigests {
    StoreManyFileDigests {
      hash: HashMap::new(),
    }
  }

  fn merge(&mut self, other: StoreManyFileDigests) {
    self.hash.extend(other.hash);
  }
}

impl StoreFileByDigest<String> for StoreManyFileDigests {
  fn store_by_digest(&self, file: File) -> BoxFuture<Digest, String> {
    future::result(self.hash.get(&file.path).copied().ok_or_else(|| {
      format!(
        "Could not find file {} when storing file by digest",
        file.path.display()
      )
    }))
    .to_boxed()
  }
}
