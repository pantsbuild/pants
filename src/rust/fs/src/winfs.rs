// Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::ffi::{OsStr, OsString};
use std::fs;
use std::io::{self, ErrorKind};
use std::path::{Component, Path, PathBuf, Prefix};
use std::sync::Arc;

use async_trait::async_trait;

use crate::directory::SymlinkBehavior;
use crate::gitignore::GitignoreStyleExcludes;
use crate::{Dir, DirectoryListing, File, Link, PathMetadata, PathMetadataKind, Stat, Vfs};

///
/// The extensions of files that WinFS reports as executable. These are the extensions in the
/// default `PATHEXT` that name programs or scripts run directly by Windows itself, rather than by
/// an interpreter that happens to be registered for them.
///
/// NB: We deliberately don't use `SaferiIsExecutableFileType`, which checks against the Software
/// Restriction Policies list of "designated file types". That list lives in the registry and can be
/// changed by Group Policy, so the same file could get a different digest on different machines.
/// (Its default list also includes non-program types such as `.lnk`, `.url` and `.reg`.)
///
const EXECUTABLE_EXTENSIONS: [&str; 4] = ["exe", "com", "bat", "cmd"];

///
/// The Windows counterpart of `PosixFS`, with the same API.
///
/// All Stats consumed or returned by this type are relative to the root.
///
/// If `symlink_behavior` is Aware (as it is by default), `scandir` will produce `Link` entries so
/// that a consumer can explicitly track their expansion. Otherwise, if Oblivious, operations will
/// allow the operating system to expand links to their underlying types without regard to the
/// links traversed, and `scandir` will produce only `Dir` and `File` entries.
///
/// Where Windows semantics differ from POSIX:
///
/// - There is no executable bit, so a file is reported as executable if its name has one of
///   `EXECUTABLE_EXTENSIONS` (case-insensitively), and `unix_mode` is always `None`. The list is
///   fixed rather than read from `PATHEXT`, so that digests do not vary between machines.
/// - Rust's standard library reports both symlinks and junctions (and any other "name surrogate"
///   reparse point) as symlinks, so they are all treated as `Link`s.
/// - A junction's target is always absolute. If it is inside the root, it is reported as the
///   equivalent relative path (e.g. `C:\repo\a\j -> C:\repo\b` is reported as `..\b`), so that the
///   junction can be traversed like a relative symlink. A junction pointing outside the root is
///   reported as-is, and so is rejected by `read_link` like any other absolute link.
/// - Link targets are reported exactly as Windows stores them, typically with `\` as the
///   separator. So a symlink's target (and therefore its digest) can differ from the same symlink's
///   on POSIX: we don't currently expect to share digests across platforms.
/// - A link target that is rooted (`\foo`) or has a drive or UNC prefix (`C:foo`, `C:\foo`,
///   `\\server\share`) is treated as absolute.
/// - Windows filesystems are case-insensitive, but paths are still matched case-sensitively, as
///   they are on (also usually case-insensitive) macOS: a glob must match the on-disk case, and
///   `Stat`s report names exactly as they are stored.
/// - The root is canonicalized with `dunce`, which (unlike `std::fs::canonicalize`) produces an
///   ordinary path such as `C:\repo` rather than a verbatim one such as `\\?\C:\repo`, since many
///   tools mishandle verbatim paths. It keeps the verbatim form only where the ordinary one would
///   mean something different, such as for paths longer than `MAX_PATH` or containing reserved
///   names like `CON`.
///
#[derive(Clone)]
pub struct WinFS {
    root: Dir,
    ignore: Arc<GitignoreStyleExcludes>,
    executor: task_executor::Executor,
    symlink_behavior: SymlinkBehavior,
}

// Non-public functions used internally by the public functions below.
impl WinFS {
    pub fn new<P: AsRef<Path>>(
        root: P,
        ignorer: Arc<GitignoreStyleExcludes>,
        executor: task_executor::Executor,
    ) -> Result<Self, String> {
        Self::new_with_symlink_behavior(root, ignorer, executor, SymlinkBehavior::Aware)
    }

    pub fn new_with_symlink_behavior<P: AsRef<Path>>(
        root: P,
        ignorer: Arc<GitignoreStyleExcludes>,
        executor: task_executor::Executor,
        symlink_behavior: SymlinkBehavior,
    ) -> Result<Self, String> {
        let root: &Path = root.as_ref();
        let canonical_root = dunce::canonicalize(root)
            .and_then(|canonical| {
                canonical.metadata().and_then(|metadata| {
                    if metadata.is_dir() {
                        Ok(Dir(canonical))
                    } else {
                        Err(io::Error::new(
                            io::ErrorKind::InvalidInput,
                            "Not a directory.",
                        ))
                    }
                })
            })
            .map_err(|e| format!("Could not canonicalize root {root:?}: {e:?}"))?;

        Ok(Self {
            root: canonical_root,
            ignore: ignorer,
            executor: executor,
            symlink_behavior: symlink_behavior,
        })
    }

    fn scandir_sync(&self, dir_relative_to_root: Dir) -> Result<DirectoryListing, io::Error> {
        let dir_abs = self.root.0.join(&dir_relative_to_root.0);
        let read_dir = dir_abs.read_dir()?;

        let mut entry_abs = dir_abs;

        let mut stats: Vec<Stat> = Vec::new();
        for dir_entry in read_dir {
            let dir_entry = dir_entry.map_err(|e| Self::scandir_error(&entry_abs, e))?;

            // Reuse the owned `file_name` as the `Stat`'s path so it's allocated only once.
            let file_name = dir_entry.file_name();
            entry_abs.push(&file_name);
            let stat = self.scan_entry(&entry_abs, file_name, &dir_entry);
            entry_abs.pop();

            if let Some(stat) = stat.map_err(|e| Self::scandir_error(&entry_abs, e))? {
                stats.push(stat);
            }
        }
        stats.sort_by(|s1, s2| s1.path().cmp(s2.path()));
        Ok(DirectoryListing(stats))
    }

    fn scandir_error(dir_abs: &Path, e: io::Error) -> io::Error {
        io::Error::new(
            e.kind(),
            format!("Failed to scan directory {dir_abs:?}: {e}"),
        )
    }

    fn scan_entry(
        &self,
        entry_abs: &Path,
        file_name: OsString,
        dir_entry: &std::fs::DirEntry,
    ) -> Result<Option<Stat>, io::Error> {
        let stat = match self.symlink_behavior {
            SymlinkBehavior::Aware => {
                // NB: On Windows, the file type comes from the directory enumeration itself, so this
                // does not require an additional syscall.
                let file_type = dir_entry.file_type()?;
                self.make_stat(entry_abs, file_name.into(), file_type)?
            }
            SymlinkBehavior::Oblivious => {
                let metadata = std::fs::metadata(entry_abs)?;
                self.make_stat(entry_abs, file_name.into(), metadata.file_type())?
            }
        };

        // It would be nice to ignore paths before stat'ing them, but git-style ignore patterns need
        // to know whether a path is a directory. The matcher takes a root-relative path, which is
        // `entry_abs` minus the root prefix (always present, since `entry_abs` is joined onto it).
        let Some(stat) = stat else {
            return Ok(None);
        };
        let rel = entry_abs
            .strip_prefix(&self.root.0)
            .expect("entry path is always under the root");
        if self
            .ignore
            .is_ignored_path(rel, matches!(stat, Stat::Dir(_)))
        {
            Ok(None)
        } else {
            Ok(Some(stat))
        }
    }

    // Makes a Stat for `path_to_stat`, deriving its directory-relative name from the final path
    // component. Callers on the directory-walk hot path use `make_stat` instead, reusing the name
    // they already own.
    fn stat_internal(
        &self,
        path_to_stat: &Path,
        file_type: std::fs::FileType,
    ) -> Result<Option<Stat>, io::Error> {
        let Some(name) = path_to_stat.file_name() else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Argument path_to_stat to WinFS::stat_internal must have a file name.",
            ));
        };
        self.make_stat(path_to_stat, name.into(), file_type)
    }

    fn make_stat(
        &self,
        abs_path: &Path,
        name: PathBuf,
        file_type: std::fs::FileType,
    ) -> Result<Option<Stat>, io::Error> {
        if cfg!(debug_assertions) && !abs_path.is_absolute() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!(
                    "Argument abs_path to WinFS::make_stat must be an absolute path, got {abs_path:?}"
                ),
            ));
        }
        if file_type.is_symlink() {
            Ok(Some(Stat::Link(Link {
                path: name,
                target: self.read_link_target(abs_path)?,
            })))
        } else if file_type.is_file() {
            let is_executable = Self::is_executable(&name);
            Ok(Some(Stat::File(File {
                path: name,
                is_executable,
            })))
        } else if file_type.is_dir() {
            Ok(Some(Stat::Dir(Dir(name))))
        } else {
            Ok(None)
        }
    }

    ///
    /// Reads the target of the link at `link_abs`, relativizing it if it is a junction to a path
    /// inside the root.
    ///
    fn read_link_target(&self, link_abs: &Path) -> Result<PathBuf, io::Error> {
        let target = fs::read_link(link_abs)?;
        // NB: Junction targets are always absolute, so only check for one if the target is.
        if Self::is_absolute_link_target(&target)
            && is_junction(link_abs)?
            && let Some(relative_target) = link_abs.parent().and_then(|link_parent| {
                relativize_junction_target(&self.root.0, link_parent, &target)
            })
        {
            return Ok(relative_target);
        }
        Ok(target)
    }

    ///
    /// Whether a file at `path` should be considered executable, based on its extension. See
    /// `EXECUTABLE_EXTENSIONS`.
    ///
    fn is_executable(path: &Path) -> bool {
        path.extension()
            .and_then(|ext| ext.to_str())
            .is_some_and(|ext| {
                EXECUTABLE_EXTENSIONS
                    .iter()
                    .any(|exe_ext| ext.eq_ignore_ascii_case(exe_ext))
            })
    }

    ///
    /// Whether a link target escapes the directory containing the link by any means other than
    /// `..`. `Path::is_absolute` is not sufficient on Windows: `\foo` (relative to the current
    /// drive) and `C:foo` (relative to the current directory on drive C) are not "absolute", but
    /// neither can be resolved relative to the link.
    ///
    fn is_absolute_link_target(target: &Path) -> bool {
        matches!(
            target.components().next(),
            Some(Component::Prefix(_)) | Some(Component::RootDir)
        )
    }
}

// Public functions used externally.
impl WinFS {
    pub async fn scandir(&self, dir_relative_to_root: Dir) -> Result<DirectoryListing, io::Error> {
        let vfs = self.clone();
        self.executor
            .spawn_blocking(move || vfs.scandir_sync(dir_relative_to_root))
            .await?
            .map_err(|e| io::Error::other(format!("Synchronous scandir failed: {e}")))
    }

    pub fn is_ignored(&self, stat: &Stat) -> bool {
        self.ignore.is_ignored(stat)
    }

    pub fn file_path(&self, file: &File) -> PathBuf {
        self.root.0.join(&file.path)
    }

    pub async fn read_link(&self, link: &Link) -> Result<PathBuf, io::Error> {
        let link_parent = link.path.parent().map(Path::to_owned);
        let link_abs = self.root.0.join(link.path.as_path());
        let vfs = self.clone();
        let link_abs_for_read = link_abs.clone();
        self.executor
            .spawn_blocking(move || vfs.read_link_target(&link_abs_for_read))
            .await?
            .and_then(|path_buf| {
                if Self::is_absolute_link_target(&path_buf) {
                    Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        format!("Absolute symlink: {path_buf:?}"),
                    ))
                } else {
                    link_parent
                        .map(|parent| parent.join(&path_buf))
                        .ok_or_else(|| {
                            io::Error::new(
                                io::ErrorKind::InvalidData,
                                format!("Symlink without a parent?: {path_buf:?}"),
                            )
                        })
                }
            })
            .map_err(|e| io::Error::new(e.kind(), format!("Failed to read link {link_abs:?}: {e}")))
    }

    ///
    /// Returns a Stat relative to its containing directory.
    ///
    /// NB: This method is synchronous because it is used to stat all files in a directory as one
    /// blocking operation as part of `scandir_sync` (as recommended by the `tokio` documentation, to
    /// avoid many small spawned tasks).
    ///
    pub fn stat_sync(&self, relative_path: &Path) -> Result<Option<Stat>, io::Error> {
        if cfg!(debug_assertions) && Self::is_absolute_link_target(relative_path) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!(
                    "Argument relative_path to WinFS::stat_sync must be relative path, got {relative_path:?}"
                ),
            ));
        }
        let abs_path = self.root.0.join(relative_path);
        let metadata = match self.symlink_behavior {
            SymlinkBehavior::Aware => fs::symlink_metadata(&abs_path),
            SymlinkBehavior::Oblivious => fs::metadata(&abs_path),
        };
        metadata
            .and_then(|metadata| self.stat_internal(&abs_path, metadata.file_type()))
            .or_else(|err| match err.kind() {
                io::ErrorKind::NotFound => Ok(None),
                _ => Err(err),
            })
    }

    pub async fn path_metadata(
        &self,
        path: PathBuf,
        follow_symlinks: bool,
    ) -> Result<Option<PathMetadata>, io::Error> {
        let abs_path = self.root.0.join(&path);
        let raw_metadata = if follow_symlinks {
            tokio::fs::metadata(&abs_path).await
        } else {
            tokio::fs::symlink_metadata(&abs_path).await
        };
        match raw_metadata {
            Ok(metadata) => {
                let (kind, symlink_target) = match metadata.file_type() {
                    ft if ft.is_symlink() => {
                        let vfs = self.clone();
                        let link_abs = abs_path.clone();
                        let symlink_target = self.executor.spawn_blocking(move || vfs.read_link_target(&link_abs)).await?.map_err(|e| io::Error::other(format!("path {abs_path:?} was previously a symlink but read_link failed: {e}")))?;
                        (PathMetadataKind::Symlink, Some(symlink_target))
                    }
                    ft if ft.is_dir() => (PathMetadataKind::Directory, None),
                    ft if ft.is_file() => (PathMetadataKind::File, None),
                    _ => unreachable!("std::fs::FileType was not a symlink, directory, or file"),
                };

                let is_executable = kind == PathMetadataKind::File && Self::is_executable(&path);

                Ok(Some(PathMetadata {
                    path,
                    kind,
                    length: metadata.len(),
                    is_executable,
                    unix_mode: None,
                    accessed: metadata.accessed().ok(),
                    created: metadata.created().ok(),
                    modified: metadata.modified().ok(),
                    symlink_target,
                }))
            }
            Err(err) if err.kind() == ErrorKind::NotFound => Ok(None),
            // A path component is a file rather than a directory: treat as not found.
            Err(err) if err.kind() == ErrorKind::NotADirectory => Ok(None),
            // Sandbox/unreadable PATH entries: skip so binary lookup can continue.
            Err(err) if err.kind() == ErrorKind::PermissionDenied => Ok(None),
            // A path containing characters that are illegal on Windows (e.g. `:` or `*`) cannot
            // exist: treat as not found.
            Err(err) if err.kind() == ErrorKind::InvalidFilename => Ok(None),
            Err(err) => Err(err),
        }
    }
}

#[async_trait]
impl Vfs<io::Error> for Arc<WinFS> {
    async fn read_link(&self, link: &Link) -> Result<PathBuf, io::Error> {
        WinFS::read_link(self, link).await
    }

    async fn scandir(&self, dir: Dir) -> Result<Arc<DirectoryListing>, io::Error> {
        Ok(Arc::new(WinFS::scandir(self, dir).await?))
    }

    async fn path_metadata(
        &self,
        path: PathBuf,
        follow_symlinks: bool,
    ) -> Result<Option<PathMetadata>, io::Error> {
        WinFS::path_metadata(self, path, follow_symlinks).await
    }

    fn is_ignored(&self, stat: &Stat) -> bool {
        WinFS::is_ignored(self, stat)
    }

    fn mk_error(msg: &str) -> io::Error {
        io::Error::other(msg)
    }
}

///
/// Whether the link at `link_abs` is a junction (a "mount point" reparse point) rather than a
/// symlink, which Rust's standard library does not distinguish.
///
fn is_junction(link_abs: &Path) -> Result<bool, io::Error> {
    use std::os::windows::ffi::OsStrExt;

    use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
    use windows_sys::Win32::Storage::FileSystem::{
        FILE_ATTRIBUTE_REPARSE_POINT, FindClose, FindFirstFileW, WIN32_FIND_DATAW,
    };
    use windows_sys::Win32::System::SystemServices::IO_REPARSE_TAG_MOUNT_POINT;

    let wide_path: Vec<u16> = link_abs
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    // SAFETY: `WIN32_FIND_DATAW` is a plain C struct for which all zeroes is a valid value,
    // `wide_path` is NUL-terminated, and the handle is closed before returning.
    let find_data = unsafe {
        let mut find_data: WIN32_FIND_DATAW = std::mem::zeroed();
        let handle = FindFirstFileW(wide_path.as_ptr(), &mut find_data);
        if handle == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        FindClose(handle);
        find_data
    };
    // NB: For a reparse point, `FindFirstFileW` reports the reparse tag in `dwReserved0`.
    Ok(
        find_data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
            && find_data.dwReserved0 == IO_REPARSE_TAG_MOUNT_POINT,
    )
}

///
/// If the junction target `target` is inside `root`, returns it as a path relative to
/// `link_parent` (the directory containing the junction, which must also be inside `root`).
/// Otherwise returns None.
///
/// All three paths must be absolute. They are compared lexically, so a verbatim path (`\\?\C:\`)
/// matches its ordinary form (`C:\`), and case-insensitively, as Windows paths usually are.
///
pub(crate) fn relativize_junction_target(
    root: &Path,
    link_parent: &Path,
    target: &Path,
) -> Option<PathBuf> {
    let root = comparable_components(root)?;
    let link_parent = comparable_components(link_parent)?;
    let target = comparable_components(target)?;

    let is_in_root = |components: &[(String, &OsStr)]| {
        components.len() >= root.len()
            && components
                .iter()
                .zip(&root)
                .all(|((key, _), (root_key, _))| key == root_key)
    };
    if !is_in_root(&link_parent) || !is_in_root(&target) {
        return None;
    }

    let common_len = link_parent
        .iter()
        .zip(&target)
        .take_while(|((parent_key, _), (target_key, _))| parent_key == target_key)
        .count();
    let mut relative_target = PathBuf::new();
    for _ in common_len..link_parent.len() {
        relative_target.push("..");
    }
    for (_, name) in &target[common_len..] {
        relative_target.push(name);
    }
    if relative_target.as_os_str().is_empty() {
        relative_target.push(".");
    }
    Some(relative_target)
}

///
/// The components of an absolute path, each as a key to compare it by and its original name.
/// Returns None for a path that isn't absolute, or whose prefix can't be compared (such as a
/// device path).
///
/// NB: Lowercasing approximates the case-insensitivity of Windows filesystems, which actually use
/// a per-volume uppercase table.
///
fn comparable_components(path: &Path) -> Option<Vec<(String, &OsStr)>> {
    let mut components = path.components();
    let Some(Component::Prefix(prefix)) = components.next() else {
        return None;
    };
    let prefix_key = match prefix.kind() {
        Prefix::Disk(drive) | Prefix::VerbatimDisk(drive) => {
            format!("{}:", char::from(drive).to_ascii_lowercase())
        }
        Prefix::UNC(server, share) | Prefix::VerbatimUNC(server, share) => format!(
            "\\\\{}\\{}",
            server.to_str()?.to_lowercase(),
            share.to_str()?.to_lowercase()
        ),
        _ => return None,
    };
    if components.next() != Some(Component::RootDir) {
        return None;
    }

    let mut result = vec![(prefix_key, OsStr::new(""))];
    for component in components {
        match component {
            Component::Normal(name) => result.push((name.to_str()?.to_lowercase(), name)),
            Component::CurDir => {}
            Component::ParentDir => {
                if result.len() > 1 {
                    result.pop();
                }
            }
            Component::Prefix(_) | Component::RootDir => return None,
        }
    }
    Some(result)
}
