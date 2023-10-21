// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashSet;
use std::ffi::OsStr;
use std::fmt::Display;
use std::iter::Iterator;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;

use async_trait::async_trait;
use futures::future::{self, TryFutureExt};
use glob::{MatchOptions, Pattern};
use lazy_static::lazy_static;
use log::warn;
use parking_lot::Mutex;

use crate::{
    Dir, GitignoreStyleExcludes, GlobExpansionConjunction, Link, LinkDepth, PathStat, Stat,
    StrictGlobMatching, SymlinkBehavior, Vfs, MAX_LINK_DEPTH,
};

static DOUBLE_STAR: &str = "**";

lazy_static! {
    pub static ref SINGLE_STAR_GLOB: Pattern = Pattern::new("*").unwrap();
    pub static ref DOUBLE_STAR_GLOB: Pattern = Pattern::new(DOUBLE_STAR).unwrap();
    static ref MISSING_GLOB_SOURCE: GlobParsedSource = GlobParsedSource(String::from(""));
    static ref PATTERN_MATCH_OPTIONS: MatchOptions = MatchOptions {
        case_sensitive: true,
        require_literal_separator: true,
        require_literal_leading_dot: false,
    };
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
pub enum PathGlob {
    Wildcard {
        canonical_dir: Dir,
        symbolic_path: PathBuf,
        wildcard: Pattern,
        link_depth: LinkDepth,
    },
    DirWildcard {
        canonical_dir: Dir,
        symbolic_path: PathBuf,
        wildcard: Pattern,
        remainder: Vec<Pattern>,
        link_depth: LinkDepth,
    },
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
struct GlobParsedSource(String);

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct PathGlobIncludeEntry {
    input: GlobParsedSource,
    globs: Vec<PathGlob>,
}

impl PathGlob {
    fn wildcard(
        canonical_dir: Dir,
        symbolic_path: PathBuf,
        wildcard: Pattern,
        link_depth: LinkDepth,
    ) -> PathGlob {
        PathGlob::Wildcard {
            canonical_dir,
            symbolic_path,
            wildcard,
            link_depth,
        }
    }

    fn dir_wildcard(
        canonical_dir: Dir,
        symbolic_path: PathBuf,
        wildcard: Pattern,
        remainder: Vec<Pattern>,
        link_depth: LinkDepth,
    ) -> PathGlob {
        PathGlob::DirWildcard {
            canonical_dir,
            symbolic_path,
            wildcard,
            remainder,
            link_depth,
        }
    }

    pub fn create(filespecs: Vec<String>) -> Result<Vec<PathGlob>, String> {
        // Getting a Vec<PathGlob> per filespec is needed to create a `PreparedPathGlobs`, but we don't
        // need that here.
        Ok(Self::spread_filespecs(filespecs)?
            .into_iter()
            .flat_map(|entry| entry.globs)
            .collect())
    }

    pub(crate) fn spread_filespecs(
        filespecs: Vec<String>,
    ) -> Result<Vec<PathGlobIncludeEntry>, String> {
        let mut spec_globs_map = Vec::new();
        for filespec in filespecs {
            let canonical_dir = Dir(PathBuf::new());
            let symbolic_path = PathBuf::new();
            let globs = PathGlob::parse(canonical_dir, symbolic_path, &filespec)?;
            spec_globs_map.push(PathGlobIncludeEntry {
                input: GlobParsedSource(filespec),
                globs,
            });
        }
        Ok(spec_globs_map)
    }

    ///
    /// Normalize the given glob pattern string by splitting it into path components, and dropping
    /// references to the current directory, and consecutive '**'s.
    ///
    fn normalize_pattern(pattern: &str) -> Result<Vec<&OsStr>, String> {
        let mut parts = Vec::new();
        let mut prev_was_doublestar = false;
        for component in Path::new(pattern).components() {
            let part = match component {
                Component::Prefix(..) | Component::RootDir => {
                    return Err(format!("Absolute paths not supported: {pattern:?}"));
                }
                Component::CurDir => continue,
                c => c.as_os_str(),
            };

            // Ignore repeated doublestar instances.
            let cur_is_doublestar = DOUBLE_STAR == part;
            if prev_was_doublestar && cur_is_doublestar {
                continue;
            }
            prev_was_doublestar = cur_is_doublestar;

            parts.push(part);
        }
        Ok(parts)
    }

    ///
    /// Given a filespec String relative to a canonical Dir and path, parse it to a normalized
    /// series of PathGlob objects.
    ///
    fn parse(
        canonical_dir: Dir,
        symbolic_path: PathBuf,
        filespec: &str,
    ) -> Result<Vec<PathGlob>, String> {
        // NB: Because the filespec is a String input, calls to `to_str_lossy` are not lossy; the
        // use of `Path` is strictly for os-independent Path parsing.
        let parts = Self::normalize_pattern(filespec)?
            .into_iter()
            .map(|part| {
                Pattern::new(&part.to_string_lossy())
                    .map_err(|e| format!("Could not parse {filespec:?} as a glob: {e:?}"))
            })
            .collect::<Result<Vec<_>, _>>()?;

        PathGlob::parse_globs(canonical_dir, symbolic_path, &parts, 0)
    }

    ///
    /// Given a filespec as Patterns, create a series of PathGlob objects.
    ///
    fn parse_globs(
        canonical_dir: Dir,
        symbolic_path: PathBuf,
        parts: &[Pattern],
        link_depth: LinkDepth,
    ) -> Result<Vec<PathGlob>, String> {
        if parts.is_empty() {
            Ok(vec![])
        } else if DOUBLE_STAR == parts[0].as_str() {
            if parts.len() == 1 {
                // Per https://git-scm.com/docs/gitignore:
                //  "A trailing '/**' matches everything inside. For example, 'abc/**' matches all files
                //  inside directory "abc", relative to the location of the .gitignore file, with infinite
                //  depth."
                return Ok(vec![
                    PathGlob::dir_wildcard(
                        canonical_dir.clone(),
                        symbolic_path.clone(),
                        SINGLE_STAR_GLOB.clone(),
                        vec![DOUBLE_STAR_GLOB.clone()],
                        link_depth,
                    ),
                    PathGlob::wildcard(
                        canonical_dir,
                        symbolic_path,
                        SINGLE_STAR_GLOB.clone(),
                        link_depth,
                    ),
                ]);
            }

            // There is a double-wildcard in a dirname of the path: double wildcards are recursive,
            // so there are two remainder possibilities: one with the double wildcard included, and the
            // other without.
            let pathglob_with_doublestar = PathGlob::dir_wildcard(
                canonical_dir.clone(),
                symbolic_path.clone(),
                SINGLE_STAR_GLOB.clone(),
                parts[0..].to_vec(),
                link_depth,
            );
            let pathglob_no_doublestar = if parts.len() == 2 {
                PathGlob::wildcard(canonical_dir, symbolic_path, parts[1].clone(), link_depth)
            } else {
                PathGlob::dir_wildcard(
                    canonical_dir,
                    symbolic_path,
                    parts[1].clone(),
                    parts[2..].to_vec(),
                    link_depth,
                )
            };
            Ok(vec![pathglob_with_doublestar, pathglob_no_doublestar])
        } else if parts[0].as_str() == Component::ParentDir.as_os_str().to_str().unwrap() {
            // A request for the parent of `canonical_dir`: since we've already expanded the directory
            // to make it canonical, we can safely drop it directly and recurse without this component.
            // The resulting symbolic path will continue to contain a literal `..`.
            let mut canonical_dir_parent = canonical_dir;
            let mut symbolic_path_parent = symbolic_path;
            if !canonical_dir_parent.0.pop() {
                let mut symbolic_path = symbolic_path_parent;
                symbolic_path.extend(parts.iter().map(Pattern::as_str));
                return Err(format!(
                    "Globs may not traverse outside of the buildroot: {symbolic_path:?}",
                ));
            }
            symbolic_path_parent.push(Path::new(&Component::ParentDir));
            PathGlob::parse_globs(
                canonical_dir_parent,
                symbolic_path_parent,
                &parts[1..],
                link_depth,
            )
        } else if parts.len() == 1 {
            // This is the path basename.
            Ok(vec![PathGlob::wildcard(
                canonical_dir,
                symbolic_path,
                parts[0].clone(),
                link_depth,
            )])
        } else {
            // This is a path dirname.
            Ok(vec![PathGlob::dir_wildcard(
                canonical_dir,
                symbolic_path,
                parts[0].clone(),
                parts[1..].to_vec(),
                link_depth,
            )])
        }
    }
}

#[derive(Debug, Clone)]
pub struct PreparedPathGlobs {
    pub(crate) include: Vec<PathGlobIncludeEntry>,
    pub(crate) exclude: Arc<GitignoreStyleExcludes>,
    strict_match_behavior: StrictGlobMatching,
    conjunction: GlobExpansionConjunction,
}

impl PreparedPathGlobs {
    pub fn create(
        globs: Vec<String>,
        strict_match_behavior: StrictGlobMatching,
        conjunction: GlobExpansionConjunction,
    ) -> Result<PreparedPathGlobs, String> {
        let mut include_globs = Vec::new();
        let mut exclude_globs = Vec::new();
        for glob in globs {
            if glob.starts_with('!') {
                let normalized_exclude: String = glob.chars().skip(1).collect();
                exclude_globs.push(normalized_exclude);
            } else {
                include_globs.push(glob);
            }
        }
        let include = PathGlob::spread_filespecs(include_globs)?;
        let exclude = GitignoreStyleExcludes::create(exclude_globs)?;

        Ok(PreparedPathGlobs {
            include,
            exclude,
            strict_match_behavior,
            conjunction,
        })
    }

    fn from_globs(include: Vec<PathGlob>) -> Result<PreparedPathGlobs, String> {
        let include: Vec<PathGlobIncludeEntry> = include
            .into_iter()
            .map(|glob| PathGlobIncludeEntry {
                input: MISSING_GLOB_SOURCE.clone(),
                globs: vec![glob],
            })
            .collect();

        Ok(PreparedPathGlobs {
            include,
            // An empty exclude becomes EMPTY_IGNORE.
            exclude: GitignoreStyleExcludes::create(vec![])?,
            strict_match_behavior: StrictGlobMatching::Ignore,
            conjunction: GlobExpansionConjunction::AllMatch,
        })
    }
}

/// Allows checking in-memory if paths match the patterns.
#[derive(Debug)]
pub struct FilespecMatcher {
    includes: Vec<Pattern>,
    excludes: Arc<GitignoreStyleExcludes>,
}

impl FilespecMatcher {
    pub fn new(includes: Vec<String>, excludes: Vec<String>) -> Result<Self, String> {
        let includes = includes
            .iter()
            .map(|glob| {
                PathGlob::normalize_pattern(glob).and_then(|components| {
                    let normalized_pattern: PathBuf = components.into_iter().collect();
                    Pattern::new(normalized_pattern.to_str().unwrap())
                        .map_err(|e| format!("Could not parse {glob:?} as a glob: {e:?}"))
                })
            })
            .collect::<Result<Vec<_>, String>>()?;
        let excludes = GitignoreStyleExcludes::create(excludes)?;
        Ok(Self { includes, excludes })
    }

    ///
    /// Matches the patterns against the given paths.
    ///
    /// NB: This implementation is independent from GlobMatchingImplementation::expand, and must be
    /// kept in sync via unit tests (in particular: the python filespec_test.py) in order to allow for
    /// owners detection of deleted files (see #6790 and #5636 for more info). The lazy filesystem
    /// traversal in expand is (currently) too expensive to use for that in-memory matching (such as
    /// via MemFS).
    ///
    pub fn matches(&self, path: &Path) -> bool {
        let matches_includes = self
            .includes
            .iter()
            .any(|pattern| pattern.matches_path_with(path, *PATTERN_MATCH_OPTIONS));
        matches_includes && !self.excludes.is_ignored_path(path, false)
    }

    pub fn include_globs(&self) -> &[Pattern] {
        self.includes.as_slice()
    }

    pub fn exclude_globs(&self) -> &[String] {
        self.excludes.exclude_patterns()
    }
}

#[async_trait]
pub trait GlobMatching<E: Display + Send + Sync + 'static>: Vfs<E> {
    ///
    /// Canonicalize the Link for the given Path to an underlying File or Dir. May result
    /// in None if the PathStat represents a broken Link.
    ///
    /// Skips ignored paths both before and after expansion.
    ///
    async fn canonicalize_link(
        &self,
        symbolic_path: PathBuf,
        link: Link,
    ) -> Result<Option<PathStat>, E> {
        GlobMatchingImplementation::canonicalize_link(self, symbolic_path, link).await
    }

    ///
    /// Recursively expands PathGlobs into PathStats while applying excludes.
    ///
    async fn expand_globs(
        &self,
        path_globs: PreparedPathGlobs,
        symlink_behavior: SymlinkBehavior,
        unmatched_globs_additional_context: Option<String>,
    ) -> Result<Vec<PathStat>, E> {
        GlobMatchingImplementation::expand_globs(
            self,
            path_globs,
            symlink_behavior,
            unmatched_globs_additional_context,
        )
        .await
    }
}

impl<E: Display + Send + Sync + 'static, T: Vfs<E>> GlobMatching<E> for T {}

// NB: This trait exists because `expand_single()` (and its return type) should be private, but
// traits don't allow specifying private methods (and we don't want to use a top-level `fn` because
// it's much more awkward than just specifying `&self`).
// The methods of `GlobMatching` are forwarded to methods here.
#[async_trait]
trait GlobMatchingImplementation<E: Display + Send + Sync + 'static>: Vfs<E> {
    async fn directory_listing(
        &self,
        canonical_dir: Dir,
        symbolic_path: PathBuf,
        wildcard: Pattern,
        exclude: &Arc<GitignoreStyleExcludes>,
        symlink_behavior: SymlinkBehavior,
        link_depth: LinkDepth,
    ) -> Result<Vec<(PathStat, LinkDepth)>, E> {
        // List the directory.
        let dir_listing = self.scandir(canonical_dir).await?;

        // Match any relevant Stats, and join them into PathStats.
        let path_stats = future::try_join_all(
            dir_listing
                .0
                .iter()
                .filter(|stat| {
                    // Match relevant filenames.
                    stat.path()
                        .file_name()
                        .map(|file_name| wildcard.matches_path(Path::new(file_name)))
                        .unwrap_or(false)
                })
                .filter_map(|stat| {
                    // Append matched filenames.
                    stat.path()
                        .file_name()
                        .map(|file_name| symbolic_path.join(file_name))
                        .map(|symbolic_stat_path| (symbolic_stat_path, stat))
                })
                .map(|(stat_symbolic_path, stat)| {
                    let context = self.clone();
                    let exclude = exclude.clone();
                    async move {
                        // Canonicalize matched PathStats, and filter paths that are ignored by local excludes.
                        // Context ("global") ignore patterns are applied during `scandir`.
                        if exclude.is_ignored(stat) {
                            Ok(None)
                        } else {
                            match stat {
                                Stat::Link(l) => {
                                    // NB: When traversing a link, we increment the link_depth.
                                    if link_depth >= MAX_LINK_DEPTH {
                                        return Err(Self::mk_error(&format!(
                      "Maximum link depth exceeded at {l:?} for {stat_symbolic_path:?}"
                    )));
                                    }

                                    if let SymlinkBehavior::Aware = symlink_behavior {
                                        return Ok(Some((
                                            PathStat::link(stat_symbolic_path, l.clone()),
                                            link_depth + 1,
                                        )));
                                    }

                                    let dest = context
                                        .canonicalize_link(stat_symbolic_path, l.clone())
                                        .await?;

                                    Ok(dest.map(|ps| (ps, link_depth + 1)))
                                }
                                Stat::Dir(d) => Ok(Some((
                                    PathStat::dir(stat_symbolic_path, d.clone()),
                                    link_depth,
                                ))),
                                Stat::File(f) => Ok(Some((
                                    PathStat::file(stat_symbolic_path, f.clone()),
                                    link_depth,
                                ))),
                            }
                        }
                    }
                })
                .collect::<Vec<_>>(),
        )
        .await?;
        // See the note above.
        Ok(path_stats.into_iter().flatten().collect())
    }

    async fn expand_globs(
        &self,
        path_globs: PreparedPathGlobs,
        symlink_behavior: SymlinkBehavior,
        unmatched_globs_additional_context: Option<String>,
    ) -> Result<Vec<PathStat>, E> {
        let PreparedPathGlobs {
            include,
            exclude,
            strict_match_behavior,
            conjunction,
            ..
        } = path_globs;

        if include.is_empty() {
            return Ok(vec![]);
        }

        let result = Arc::new(Mutex::new(Vec::new()));

        let mut sources = Vec::new();
        let mut roots = Vec::new();
        for pgie in include {
            let source = Arc::new(pgie.input);
            for path_glob in pgie.globs {
                sources.push(source.clone());
                roots.push(self.expand_single(
                    result.clone(),
                    exclude.clone(),
                    path_glob,
                    symlink_behavior,
                ));
            }
        }

        let matched = future::try_join_all(roots).await?;

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
                let mut non_matching_inputs = non_matching_inputs
                    .iter()
                    .map(|parsed_source| parsed_source.0.clone())
                    .collect::<Vec<_>>();
                non_matching_inputs.sort();
                let single_glob = non_matching_inputs.len() == 1;
                let prefix = format!("Unmatched glob{}", if single_glob { "" } else { "s" });
                let origin = match &strict_match_behavior {
                    StrictGlobMatching::Warn(description)
                    | StrictGlobMatching::Error(description) => {
                        format!(" from {description}: ")
                    }
                    _ => ": ".to_string(),
                };
                let unmatched_globs = if single_glob {
                    format!("{:?}", non_matching_inputs[0])
                } else {
                    format!("{non_matching_inputs:?}")
                };
                let exclude_patterns = exclude.exclude_patterns();
                let excludes_portion = if exclude_patterns.is_empty() {
                    "".to_string()
                } else {
                    let single_exclude = exclude_patterns.len() == 1;
                    if single_exclude {
                        format!(", exclude: {:?}", exclude_patterns[0])
                    } else {
                        format!(", excludes: {exclude_patterns:?}")
                    }
                };
                let msg = format!(
                    "{}{}{}{}{}",
                    prefix,
                    origin,
                    unmatched_globs,
                    excludes_portion,
                    unmatched_globs_additional_context.unwrap_or_else(|| "".to_owned())
                );
                if strict_match_behavior.should_throw_on_error() {
                    return Err(Self::mk_error(&msg));
                } else {
                    warn!("{}", msg);
                }
            }
        }

        let mut path_stats = Arc::try_unwrap(result)
            .unwrap_or_else(|_| panic!("expand violated its contract."))
            .into_inner()
            .into_iter()
            .collect::<Vec<_>>();
        #[allow(clippy::unnecessary_sort_by)]
        path_stats.sort_by(|a, b| a.path().cmp(b.path()));
        path_stats.dedup_by(|a, b| a.path() == b.path());
        Ok(path_stats)
    }

    async fn expand_single(
        &self,
        result: Arc<Mutex<Vec<PathStat>>>,
        exclude: Arc<GitignoreStyleExcludes>,
        path_glob: PathGlob,
        symlink_behavior: SymlinkBehavior,
    ) -> Result<bool, E> {
        match path_glob {
            PathGlob::Wildcard {
                canonical_dir,
                symbolic_path,
                wildcard,
                link_depth,
            } => {
                self.expand_wildcard(
                    result,
                    exclude,
                    canonical_dir,
                    symbolic_path,
                    wildcard,
                    symlink_behavior,
                    link_depth,
                )
                .await
            }
            PathGlob::DirWildcard {
                canonical_dir,
                symbolic_path,
                wildcard,
                remainder,
                link_depth,
            } => {
                self.expand_dir_wildcard(
                    result,
                    exclude,
                    canonical_dir,
                    symbolic_path,
                    wildcard,
                    remainder,
                    symlink_behavior,
                    link_depth,
                )
                .await
            }
        }
    }

    async fn expand_wildcard(
        &self,
        result: Arc<Mutex<Vec<PathStat>>>,
        exclude: Arc<GitignoreStyleExcludes>,
        canonical_dir: Dir,
        symbolic_path: PathBuf,
        wildcard: Pattern,
        symlink_behavior: SymlinkBehavior,
        link_depth: LinkDepth,
    ) -> Result<bool, E> {
        // Filter directory listing to append PathStats, with no continuation.
        let path_stats = self
            .directory_listing(
                canonical_dir,
                symbolic_path,
                wildcard,
                &exclude,
                symlink_behavior,
                link_depth,
            )
            .await?;

        let mut result = result.lock();
        let matched = !path_stats.is_empty();
        result.extend(path_stats.into_iter().map(|(ps, _)| ps));
        Ok(matched)
    }

    async fn expand_dir_wildcard(
        &self,
        result: Arc<Mutex<Vec<PathStat>>>,
        exclude: Arc<GitignoreStyleExcludes>,
        canonical_dir: Dir,
        symbolic_path: PathBuf,
        wildcard: Pattern,
        remainder: Vec<Pattern>,
        symlink_behavior: SymlinkBehavior,
        link_depth: LinkDepth,
    ) -> Result<bool, E> {
        // Filter directory listing and recurse for matched Dirs.
        let context = self.clone();
        let path_stats = self
            .directory_listing(
                canonical_dir,
                symbolic_path,
                wildcard,
                &exclude,
                symlink_behavior,
                link_depth,
            )
            .await?;

        let path_globs = path_stats
            .into_iter()
            .filter_map(|(ps, link_depth)| match ps {
                PathStat::Dir { path, stat } => Some(
                    PathGlob::parse_globs(stat, path, &remainder, link_depth)
                        .map_err(|e| Self::mk_error(e.as_str())),
                ),
                PathStat::Link { .. } => None,
                PathStat::File { .. } => None,
            })
            .collect::<Result<Vec<_>, E>>()?;

        let child_globs = path_globs
            .into_iter()
            .flat_map(Vec::into_iter)
            .map(|pg| context.expand_single(result.clone(), exclude.clone(), pg, symlink_behavior))
            .collect::<Vec<_>>();

        let child_matches = future::try_join_all(child_globs).await?;
        Ok(child_matches.into_iter().any(|m| m))
    }

    async fn canonicalize_link(
        &self,
        symbolic_path: PathBuf,
        link: Link,
    ) -> Result<Option<PathStat>, E> {
        // Read the link, which may result in PathGlob(s) that match 0 or 1 Path.
        let context = self.clone();
        // If the link destination can't be parsed as PathGlob(s), it is broken.
        let link_globs = self
            .read_link(&link)
            .await?
            .to_str()
            .and_then(|dest_str| {
                // Escape any globs in the parsed dest, which should guarantee one output PathGlob.
                PathGlob::create(vec![Pattern::escape(dest_str)]).ok()
            })
            .unwrap_or_default();

        let path_globs =
            PreparedPathGlobs::from_globs(link_globs).map_err(|e| Self::mk_error(e.as_str()))?;
        let mut path_stats = context
            .expand_globs(path_globs, SymlinkBehavior::Oblivious, None)
            .map_err(move |e| {
                Self::mk_error(&format!("While expanding link {:?}: {}", link.path, e))
            })
            .await?;

        // Since we've escaped any globs in the parsed path, expect either 0 or 1 destination.
        Ok(path_stats.pop().map(|ps| match ps {
            PathStat::Dir { stat, .. } => PathStat::dir(symbolic_path, stat),
            PathStat::File { stat, .. } => PathStat::file(symbolic_path, stat),
            PathStat::Link { stat, .. } => PathStat::link(symbolic_path, stat),
        }))
    }
}

impl<E: Display + Send + Sync + 'static, T: Vfs<E>> GlobMatchingImplementation<E> for T {}
