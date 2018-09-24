// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use boxfuture::{BoxFuture, Boxable};
use futures::future;
use futures::Future;
use glob::Pattern;
use indexmap::{map::Entry::Occupied, IndexMap, IndexSet};

use {
  Dir, GitignoreStyleExcludes, GlobExpansionConjunction, GlobParsedSource, GlobSource,
  GlobWithSource, Link, PathGlob, PathGlobs, PathStat, Stat, VFS,
};

pub trait GlobMatching<E: Send + Sync + 'static>: VFS<E> {
  ///
  /// Canonicalize the Link for the given Path to an underlying File or Dir. May result
  /// in None if the PathStat represents a broken Link.
  ///
  /// Skips ignored paths both before and after expansion.
  ///
  /// TODO: Should handle symlink loops (which would exhibit as an infinite loop in expand).
  ///
  fn canonicalize(&self, symbolic_path: PathBuf, link: &Link) -> BoxFuture<Option<PathStat>, E> {
    GlobMatchingImplementation::canonicalize(self, symbolic_path, link)
  }

  ///
  /// Recursively expands PathGlobs into PathStats while applying excludes.
  ///
  fn expand(&self, path_globs: PathGlobs) -> BoxFuture<Vec<PathStat>, E> {
    GlobMatchingImplementation::expand(self, path_globs)
  }
}

impl<E: Send + Sync + 'static, T: VFS<E>> GlobMatching<E> for T {}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
enum GlobMatch {
  SuccessfullyMatchedSomeFiles,
  DidNotMatchAnyFiles,
}

#[derive(Debug)]
struct GlobExpansionCacheEntry {
  globs: Vec<PathGlob>,
  matched: GlobMatch,
  sources: Vec<GlobSource>,
}

#[derive(Debug)]
struct SingleExpansionResult {
  sourced_glob: GlobWithSource,
  path_stats: Vec<PathStat>,
  globs: Vec<PathGlob>,
}

#[derive(Debug)]
struct PathGlobsExpansion<T: Sized> {
  context: T,
  // Globs that have yet to be expanded, in order.
  todo: Vec<GlobWithSource>,
  // Paths to exclude.
  exclude: Arc<GitignoreStyleExcludes>,
  // Globs that have already been expanded.
  completed: IndexMap<PathGlob, GlobExpansionCacheEntry>,
  // Unique Paths that have been matched, in order.
  outputs: IndexSet<PathStat>,
}

// NB: This trait exists because `expand_single()` (and its return type) should be private, but
// traits don't allow specifying private methods (and we don't want to use a top-level `fn` because
// it's much more awkward than just specifying `&self`).
// The methods of `GlobMatching` are forwarded to methods here.
trait GlobMatchingImplementation<E: Send + Sync + 'static>: VFS<E> {
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
            }).filter_map(|stat| {
              // Append matched filenames.
              stat
                .path()
                .file_name()
                .map(|file_name| symbolic_path.join(file_name))
                .map(|symbolic_stat_path| (symbolic_stat_path, stat))
            }).map(|(stat_symbolic_path, stat)| {
              // Canonicalize matched PathStats, and filter paths that are ignored by either the
              // context, or by local excludes. Note that we apply context ignore patterns to both
              // the symbolic and canonical names of Links, but only apply local excludes to their
              // symbolic names.
              if context.is_ignored(&stat) || exclude.is_ignored(&stat) {
                future::ok(None).to_boxed()
              } else {
                match stat {
                  Stat::Link(l) => context.canonicalize(stat_symbolic_path, l),
                  Stat::Dir(d) => future::ok(Some(PathStat::dir(
                    stat_symbolic_path.to_owned(),
                    d.clone(),
                  ))).to_boxed(),
                  Stat::File(f) => future::ok(Some(PathStat::file(
                    stat_symbolic_path.to_owned(),
                    f.clone(),
                  ))).to_boxed(),
                }
              }
            }).collect::<Vec<_>>(),
        )
      }).map(|path_stats| {
        // See the note above.
        path_stats.into_iter().filter_map(|pso| pso).collect()
      }).to_boxed()
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

    let init = PathGlobsExpansion {
      context: self.clone(),
      todo: include
        .iter()
        .flat_map(|entry| entry.to_sourced_globs())
        .collect(),
      exclude,
      completed: IndexMap::default(),
      outputs: IndexSet::default(),
    };
    future::loop_fn(init, |mut expansion| {
      // Request the expansion of all outstanding PathGlobs as a batch.
      let round = future::join_all({
        let exclude = &expansion.exclude;
        let context = &expansion.context;
        expansion
          .todo
          .drain(..)
          .map(|sourced_glob| context.expand_single(sourced_glob, exclude))
          .collect::<Vec<_>>()
      });
      round.map(move |single_expansion_results| {
        // Collect distinct new PathStats and PathGlobs
        for exp in single_expansion_results {
          let SingleExpansionResult {
            sourced_glob: GlobWithSource { path_glob, source },
            path_stats,
            globs,
          } = exp;

          expansion.outputs.extend(path_stats.clone());

          expansion
            .completed
            .entry(path_glob.clone())
            .or_insert_with(|| GlobExpansionCacheEntry {
              globs: globs.clone(),
              matched: if path_stats.is_empty() {
                GlobMatch::DidNotMatchAnyFiles
              } else {
                GlobMatch::SuccessfullyMatchedSomeFiles
              },
              sources: vec![],
            }).sources
            .push(source);

          // Do we need to worry about cloning for all these `GlobSource`s (each containing a
          // `PathGlob`)?
          let source_for_children = GlobSource::ParentGlob(path_glob);
          for child_glob in globs {
            if let Occupied(mut entry) = expansion.completed.entry(child_glob.clone()) {
              entry.get_mut().sources.push(source_for_children.clone());
            } else {
              expansion.todo.push(GlobWithSource {
                path_glob: child_glob,
                source: source_for_children.clone(),
              });
            }
          }
        }

        // If there were any new PathGlobs, continue the expansion.
        if expansion.todo.is_empty() {
          future::Loop::Break(expansion)
        } else {
          future::Loop::Continue(expansion)
        }
      })
    }).and_then(move |final_expansion| {
      // Finally, capture the resulting PathStats from the expansion.
      let PathGlobsExpansion {
        outputs,
        mut completed,
        exclude,
        ..
      } = final_expansion;

      let match_results: Vec<_> = outputs.into_iter().collect();

      if strict_match_behavior.should_check_glob_matches() {
        // Each `GlobExpansionCacheEntry` stored in `completed` for some `PathGlob` has the field
        // `matched` to denote whether that specific `PathGlob` matched any files. We propagate a
        // positive `matched` condition to all transitive "parents" of any glob which expands to
        // some non-empty set of `PathStat`s. The `sources` field contains the parents (see the enum
        // `GlobSource`), which may be another glob, or it might be a `GlobParsedSource`. We record
        // all `GlobParsedSource` inputs which transitively expanded to some file here, and below we
        // warn or error if some of the inputs were not found.
        let mut inputs_with_matches: HashSet<GlobParsedSource> = HashSet::new();

        // `completed` is an IndexMap, and we immediately insert every glob we expand into
        // `completed`, recording any `PathStat`s and `PathGlob`s it expanded to (and then expanding
        // those child globs in the next iteration of the loop_fn). If we iterate in
        // reverse order of expansion (using .rev()), we ensure that we have already visited every
        // "child" glob of the glob we are operating on while iterating. This is a reverse
        // "topological ordering" which preserves the partial order from parent to child globs.
        let all_globs: Vec<PathGlob> = completed.keys().rev().cloned().collect();
        for cur_glob in all_globs {
          // Note that we talk of "parents" and "childen", but this structure is actually a DAG,
          // because different `DirWildcard`s can potentially expand (transitively) to the same
          // intermediate glob. The "parents" of each glob are stored in the `sources` field of its
          // `GlobExpansionCacheEntry` (which is mutably updated with any new parents on each
          // iteration of the loop_fn above). This can be considered "amortized" and/or "memoized",
          // because we only traverse every parent -> child link once.
          let new_matched_source_globs = match completed.get(&cur_glob).unwrap() {
            &GlobExpansionCacheEntry {
              ref matched,
              ref sources,
              ..
            } => match matched {
              // Neither this glob, nor any of its children, expanded to any `PathStat`s, so we have
              // nothing to propagate.
              &GlobMatch::DidNotMatchAnyFiles => vec![],
              &GlobMatch::SuccessfullyMatchedSomeFiles => sources
                .iter()
                .filter_map(|src| match src {
                  // This glob matched some files, so its parent also matched some files.
                  &GlobSource::ParentGlob(ref path_glob) => Some(path_glob.clone()),
                  // We've found one of the root inputs, coming from a glob which transitively
                  // matched some child -- record it (this may already exist in the set).
                  &GlobSource::ParsedInput(ref parsed_source) => {
                    inputs_with_matches.insert(parsed_source.clone());
                    None
                  }
                }).collect(),
            },
          };
          new_matched_source_globs.into_iter().for_each(|path_glob| {
            // Overwrite whatever was in there before -- we now know these globs transitively
            // expanded to some non-empty set of `PathStat`s.
            let entry = completed.get_mut(&path_glob).unwrap();
            entry.matched = GlobMatch::SuccessfullyMatchedSomeFiles;
          });
        }

        // Get all the inputs which didn't transitively expand to any files.
        let non_matching_inputs: Vec<GlobParsedSource> = include
          .clone()
          .into_iter()
          .map(|entry| entry.input)
          .filter(|parsed_source| !inputs_with_matches.contains(parsed_source))
          .collect();

        let match_failed = match conjunction {
          // All must match.
          GlobExpansionConjunction::AllMatch => !non_matching_inputs.is_empty(),
          // Only one needs to match.
          GlobExpansionConjunction::AnyMatch => include.len() <= non_matching_inputs.len(),
        };

        if match_failed {
          // TODO(#5684): explain what global and/or target-specific option to set to
          // modify this behavior!
          let msg = format!(
            "Globs did not match. Excludes were: {:?}. Unmatched globs were: {:?}.",
            exclude.exclude_patterns(),
            non_matching_inputs
              .iter()
              .map(|parsed_source| parsed_source.0.clone())
              .collect::<Vec<_>>(),
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

      future::ok(match_results)
    }).to_boxed()
  }

  ///
  /// Apply a PathGlob, returning PathStats and additional PathGlobs that are needed for the
  /// expansion.
  ///
  fn expand_single(
    &self,
    sourced_glob: GlobWithSource,
    exclude: &Arc<GitignoreStyleExcludes>,
  ) -> BoxFuture<SingleExpansionResult, E> {
    match sourced_glob.path_glob.clone() {
      PathGlob::Wildcard {
        canonical_dir,
        symbolic_path,
        wildcard,
      } =>
      // Filter directory listing to return PathStats, with no continuation.
      {
        self
          .directory_listing(canonical_dir, symbolic_path, wildcard, exclude)
          .map(move |path_stats| SingleExpansionResult {
            sourced_glob,
            path_stats,
            globs: vec![],
          }).to_boxed()
      }
      PathGlob::DirWildcard {
        canonical_dir,
        symbolic_path,
        wildcard,
        remainder,
      } =>
      // Filter directory listing and request additional PathGlobs for matched Dirs.
      {
        self
          .directory_listing(canonical_dir, symbolic_path, wildcard, exclude)
          .and_then(move |path_stats| {
            path_stats
              .into_iter()
              .filter_map(|ps| match ps {
                PathStat::Dir { path, stat } => Some(
                  PathGlob::parse_globs(stat, path, &remainder)
                    .map_err(|e| Self::mk_error(e.as_str())),
                ),
                PathStat::File { .. } => None,
              }).collect::<Result<Vec<_>, E>>()
          }).map(move |path_globs| {
            let flattened = path_globs
              .into_iter()
              .flat_map(|path_globs| path_globs.into_iter())
              .collect();
            SingleExpansionResult {
              sourced_glob,
              path_stats: vec![],
              globs: flattened,
            }
          }).to_boxed()
      }
    }
  }

  fn canonicalize(&self, symbolic_path: PathBuf, link: &Link) -> BoxFuture<Option<PathStat>, E> {
    // Read the link, which may result in PathGlob(s) that match 0 or 1 Path.
    let context = self.clone();
    self
      .read_link(link)
      .map(|dest_path| {
        // If the link destination can't be parsed as PathGlob(s), it is broken.
        dest_path
          .to_str()
          .and_then(|dest_str| {
            // Escape any globs in the parsed dest, which should guarantee one output PathGlob.
            PathGlob::create(&[Pattern::escape(dest_str)]).ok()
          }).unwrap_or_else(|| vec![])
      }).and_then(|link_globs| {
        let new_path_globs =
          future::result(PathGlobs::from_globs(link_globs)).map_err(|e| Self::mk_error(e.as_str()));
        new_path_globs.and_then(move |path_globs| context.expand(path_globs))
      }).map(|mut path_stats| {
        // Since we've escaped any globs in the parsed path, expect either 0 or 1 destination.
        path_stats.pop().map(|ps| match ps {
          PathStat::Dir { stat, .. } => PathStat::dir(symbolic_path, stat),
          PathStat::File { stat, .. } => PathStat::file(symbolic_path, stat),
        })
      }).to_boxed()
  }
}

impl<E: Send + Sync + 'static, T: VFS<E>> GlobMatchingImplementation<E> for T {}
