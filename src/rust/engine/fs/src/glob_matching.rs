// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashSet;
use std::fmt::Display;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use boxfuture::{BoxFuture, Boxable};
use futures::future;
use futures::Future;
use glob::Pattern;
use indexmap::IndexSet;
use log::warn;
use parking_lot::Mutex;

use crate::{
  Dir, GitignoreStyleExcludes, GlobExpansionConjunction, Link, PathGlob, PathGlobs, PathStat, Stat,
  VFS,
};

pub trait GlobMatching<E: Display + Send + Sync + 'static>: VFS<E> {
  ///
  /// Canonicalize the Link for the given Path to an underlying File or Dir. May result
  /// in None if the PathStat represents a broken Link.
  ///
  /// Skips ignored paths both before and after expansion.
  ///
  /// TODO: Should handle symlink loops (which would exhibit as an infinite loop in expand).
  ///
  fn canonicalize(&self, symbolic_path: PathBuf, link: Link) -> BoxFuture<Option<PathStat>, E> {
    GlobMatchingImplementation::canonicalize(self, symbolic_path, link)
  }

  ///
  /// Recursively expands PathGlobs into PathStats while applying excludes.
  ///
  fn expand(&self, path_globs: PathGlobs) -> BoxFuture<Vec<PathStat>, E> {
    GlobMatchingImplementation::expand(self, path_globs)
  }
}

impl<E: Display + Send + Sync + 'static, T: VFS<E>> GlobMatching<E> for T {}

// NB: This trait exists because `expand_single()` (and its return type) should be private, but
// traits don't allow specifying private methods (and we don't want to use a top-level `fn` because
// it's much more awkward than just specifying `&self`).
// The methods of `GlobMatching` are forwarded to methods here.
trait GlobMatchingImplementation<E: Display + Send + Sync + 'static>: VFS<E> {
  fn directory_listing(
    &self,
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: Pattern,
    exclude: &Arc<GitignoreStyleExcludes>,
  ) -> BoxFuture<Vec<PathStat>, E> {
    // List the directory.
    let context = self.clone();
    let exclude = exclude.clone();

    self
      .scandir(canonical_dir)
      .and_then(move |dir_listing| {
        // Match any relevant Stats, and join them into PathStats.
        future::join_all(
          dir_listing
            .0
            .iter()
            .filter(|stat| {
              // Match relevant filenames.
              stat
                .path()
                .file_name()
                .map(|file_name| wildcard.matches_path(Path::new(file_name)))
                .unwrap_or(false)
            })
            .filter_map(|stat| {
              // Append matched filenames.
              stat
                .path()
                .file_name()
                .map(|file_name| symbolic_path.join(file_name))
                .map(|symbolic_stat_path| (symbolic_stat_path, stat))
            })
            .map(|(stat_symbolic_path, stat)| {
              // Canonicalize matched PathStats, and filter paths that are ignored by local excludes.
              // Context ("global") ignore patterns are applied during `scandir`.
              if exclude.is_ignored(&stat) {
                future::ok(None).to_boxed()
              } else {
                match stat {
                  Stat::Link(l) => context.canonicalize(stat_symbolic_path, l.clone()),
                  Stat::Dir(d) => future::ok(Some(PathStat::dir(
                    stat_symbolic_path.to_owned(),
                    d.clone(),
                  )))
                  .to_boxed(),
                  Stat::File(f) => future::ok(Some(PathStat::file(
                    stat_symbolic_path.to_owned(),
                    f.clone(),
                  )))
                  .to_boxed(),
                }
              }
            })
            .collect::<Vec<_>>(),
        )
      })
      .map(|path_stats| {
        // See the note above.
        path_stats.into_iter().filter_map(|pso| pso).collect()
      })
      .to_boxed()
  }

  fn expand(&self, path_globs: PathGlobs) -> BoxFuture<Vec<PathStat>, E> {
    let PathGlobs {
      include,
      exclude,
      strict_match_behavior,
      conjunction,
    } = path_globs;

    if include.is_empty() {
      return future::ok(vec![]).to_boxed();
    }

    let result = Arc::new(Mutex::new(IndexSet::default()));

    let mut sources = Vec::new();
    let mut roots = Vec::new();
    for pgie in include {
      let source = Arc::new(pgie.input);
      for path_glob in pgie.globs {
        sources.push(source.clone());
        roots.push(self.expand_single(result.clone(), exclude.clone(), path_glob));
      }
    }

    future::join_all(roots)
      .and_then(move |matched| {
        if strict_match_behavior.should_check_glob_matches() {
          // Get all the inputs which didn't transitively expand to any files.
          let matching_inputs = sources
            .iter()
            .zip(matched.into_iter())
            .filter_map(
              |(source, matched)| {
                if matched {
                  Some(source.clone())
                } else {
                  None
                }
              },
            )
            .collect::<HashSet<_>>();

          let non_matching_inputs = sources
            .into_iter()
            .filter(|s| !matching_inputs.contains(s))
            .collect::<HashSet<_>>();

          let match_failed = match conjunction {
            // All must match.
            GlobExpansionConjunction::AllMatch => !non_matching_inputs.is_empty(),
            // Only one needs to match.
            GlobExpansionConjunction::AnyMatch => matching_inputs.is_empty(),
          };

          if match_failed {
            // TODO(#5684): explain what global and/or target-specific option to set to
            // modify this behavior!
            let mut non_matching_inputs = non_matching_inputs
              .iter()
              .map(|parsed_source| parsed_source.0.clone())
              .collect::<Vec<_>>();
            non_matching_inputs.sort();
            let msg = format!(
              "Globs did not match. Excludes were: {:?}. Unmatched globs were: {:?}.",
              exclude.exclude_patterns(),
              non_matching_inputs,
            );
            if strict_match_behavior.should_throw_on_error() {
              return future::err(Self::mk_error(&msg));
            } else {
              // TODO(#5683): this doesn't have any useful context (the stack trace) without
              // being thrown -- this needs to be provided, otherwise this is far less useful.
              warn!("{}", msg);
            }
          }
        }

        future::ok(
          Arc::try_unwrap(result)
            .unwrap_or_else(|_| panic!("expand violated its contract."))
            .into_inner()
            .into_iter()
            .collect::<Vec<_>>(),
        )
      })
      .to_boxed()
  }

  fn expand_single(
    &self,
    result: Arc<Mutex<IndexSet<PathStat>>>,
    exclude: Arc<GitignoreStyleExcludes>,
    path_glob: PathGlob,
  ) -> BoxFuture<bool, E> {
    match path_glob {
      PathGlob::Wildcard {
        canonical_dir,
        symbolic_path,
        wildcard,
      } => self.expand_wildcard(
        result.clone(),
        exclude.clone(),
        canonical_dir,
        symbolic_path,
        wildcard,
      ),
      PathGlob::DirWildcard {
        canonical_dir,
        symbolic_path,
        wildcard,
        remainder,
      } => self.expand_dir_wildcard(
        result.clone(),
        exclude.clone(),
        canonical_dir,
        symbolic_path,
        wildcard,
        remainder,
      ),
    }
  }

  fn expand_wildcard(
    &self,
    result: Arc<Mutex<IndexSet<PathStat>>>,
    exclude: Arc<GitignoreStyleExcludes>,
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: Pattern,
  ) -> BoxFuture<bool, E> {
    // Filter directory listing to append PathStats, with no continuation.
    self
      .directory_listing(canonical_dir, symbolic_path, wildcard, &exclude)
      .map(move |path_stats| {
        let mut result = result.lock();
        let matched = !path_stats.is_empty();
        result.extend(path_stats);
        matched
      })
      .to_boxed()
  }

  fn expand_dir_wildcard(
    &self,
    result: Arc<Mutex<IndexSet<PathStat>>>,
    exclude: Arc<GitignoreStyleExcludes>,
    canonical_dir: Dir,
    symbolic_path: PathBuf,
    wildcard: Pattern,
    remainder: Vec<Pattern>,
  ) -> BoxFuture<bool, E> {
    // Filter directory listing and recurse for matched Dirs.
    let context = self.clone();
    self
      .directory_listing(canonical_dir, symbolic_path, wildcard, &exclude)
      .and_then(move |path_stats| {
        path_stats
          .into_iter()
          .filter_map(|ps| match ps {
            PathStat::Dir { path, stat } => Some(
              PathGlob::parse_globs(stat, path, &remainder).map_err(|e| Self::mk_error(e.as_str())),
            ),
            PathStat::File { .. } => None,
          })
          .collect::<Result<Vec<_>, E>>()
      })
      .and_then(move |path_globs| {
        let child_globs = path_globs
          .into_iter()
          .flat_map(|path_globs| path_globs.into_iter())
          .map(|pg| context.expand_single(result.clone(), exclude.clone(), pg))
          .collect::<Vec<_>>();
        future::join_all(child_globs)
          .map(|child_matches| child_matches.into_iter().any(|m| m))
          .to_boxed()
      })
      .to_boxed()
  }

  fn canonicalize(&self, symbolic_path: PathBuf, link: Link) -> BoxFuture<Option<PathStat>, E> {
    // Read the link, which may result in PathGlob(s) that match 0 or 1 Path.
    let context = self.clone();
    self
      .read_link(&link)
      .map(|dest_path| {
        // If the link destination can't be parsed as PathGlob(s), it is broken.
        dest_path
          .to_str()
          .and_then(|dest_str| {
            // Escape any globs in the parsed dest, which should guarantee one output PathGlob.
            PathGlob::create(&[Pattern::escape(dest_str)]).ok()
          })
          .unwrap_or_else(|| vec![])
      })
      .and_then(move |link_globs| {
        future::result(PathGlobs::from_globs(link_globs))
          .map_err(|e| Self::mk_error(e.as_str()))
          .and_then(move |path_globs| context.expand(path_globs))
      })
      .map_err(move |e| Self::mk_error(&format!("While expanding link {:?}: {}", link.0, e)))
      .map(|mut path_stats| {
        // Since we've escaped any globs in the parsed path, expect either 0 or 1 destination.
        path_stats.pop().map(|ps| match ps {
          PathStat::Dir { stat, .. } => PathStat::dir(symbolic_path, stat),
          PathStat::File { stat, .. } => PathStat::file(symbolic_path, stat),
        })
      })
      .to_boxed()
  }
}

impl<E: Display + Send + Sync + 'static, T: VFS<E>> GlobMatchingImplementation<E> for T {}
