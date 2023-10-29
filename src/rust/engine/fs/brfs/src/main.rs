// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
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
    clippy::used_underscore_binding
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
#![type_length_limit = "44109434"]

use std::collections::hash_map::Entry::{Occupied, Vacant};
use std::collections::{BTreeMap, HashMap};
use std::ffi::{OsStr, OsString};
use std::path::Path;
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;
use std::time;

use clap::{Arg, Command};
use futures::future::FutureExt;
use grpc_util::tls;
use hashing::{Digest, Fingerprint};
use log::{debug, error, warn};
use parking_lot::Mutex;
use protos::gen::build::bazel::remote::execution::v2 as remexec;
use protos::require_digest;
use store::{RemoteStoreOptions, Store, StoreError};
use tokio::signal::unix::{signal, SignalKind};
use tokio::task;
use tokio_stream::wrappers::SignalStream;
use tokio_stream::StreamExt;

const TTL: time::Duration = time::Duration::from_secs(0);

const CREATE_TIME: time::SystemTime = time::SystemTime::UNIX_EPOCH;

fn dir_attr_for(inode: Inode) -> fuser::FileAttr {
    attr_for(inode, 0, fuser::FileType::Directory, 0x555)
}

fn attr_for(inode: Inode, size: u64, kind: fuser::FileType, perm: u16) -> fuser::FileAttr {
    fuser::FileAttr {
        ino: inode,
        size: size,
        // TODO: Find out whether blocks is actually important
        blocks: 0,
        atime: CREATE_TIME,
        mtime: CREATE_TIME,
        ctime: CREATE_TIME,
        crtime: CREATE_TIME,
        kind: kind,
        perm: perm,
        nlink: 1,
        uid: 0,
        gid: 0,
        rdev: 0,
        // TODO: Find out whether blksize is actually important
        blksize: 1,
        flags: 0,
    }
}

pub fn digest_from_filepath(str: &str) -> Result<Digest, String> {
    let mut parts = str.split('-');
    let fingerprint_str = parts
        .next()
        .ok_or_else(|| format!("Invalid digest: {str} wasn't of form fingerprint-size"))?;
    let fingerprint = Fingerprint::from_hex_string(fingerprint_str)?;
    let size_bytes = parts
        .next()
        .ok_or_else(|| format!("Invalid digest: {str} wasn't of form fingerprint-size"))?
        .parse::<usize>()
        .map_err(|err| format!("Invalid digest; size {str} not a number: {err}"))?;
    Ok(Digest::new(fingerprint, size_bytes))
}

type Inode = u64;

const ROOT: Inode = 1;
const DIGEST_ROOT: Inode = 2;
const DIRECTORY_ROOT: Inode = 3;

#[derive(Clone, Copy, Debug)]
enum EntryType {
    File,
    Directory,
}

#[derive(Clone, Copy, Debug)]
struct InodeDetails {
    digest: Digest,
    entry_type: EntryType,
    is_executable: bool,
}

#[derive(Debug)]
struct ReaddirEntry {
    inode: Inode,
    kind: fuser::FileType,
    name: OsString,
}

enum Node {
    Directory(remexec::DirectoryNode),
    File(remexec::FileNode),
}

#[derive(Clone, Copy, Debug)]
pub enum BRFSEvent {
    Init,
    Destroy,
}

struct BuildResultFS {
    sender: Sender<BRFSEvent>,
    runtime: task_executor::Executor,
    store: Store,
    inode_digest_cache: HashMap<Inode, InodeDetails>,
    digest_inode_cache: HashMap<Digest, (Inode, Inode)>,
    directory_inode_cache: HashMap<Digest, Inode>,
    next_inode: Inode,
}

impl BuildResultFS {
    pub fn new(
        sender: Sender<BRFSEvent>,
        runtime: task_executor::Executor,
        store: Store,
    ) -> BuildResultFS {
        BuildResultFS {
            sender: sender,
            runtime: runtime,
            store: store,
            inode_digest_cache: HashMap::new(),
            digest_inode_cache: HashMap::new(),
            directory_inode_cache: HashMap::new(),
            next_inode: 4,
        }
    }
}

impl BuildResultFS {
    pub fn node_for_digest(
        &mut self,
        directory: &remexec::Directory,
        filename: &str,
    ) -> Option<Node> {
        for file in &directory.files {
            if file.name == filename {
                return Some(Node::File(file.clone()));
            }
        }
        for child in &directory.directories {
            if child.name == filename {
                return Some(Node::Directory(child.clone()));
            }
        }
        None
    }

    pub fn inode_for_file(
        &mut self,
        digest: Digest,
        is_executable: bool,
    ) -> Result<Option<Inode>, String> {
        match self.digest_inode_cache.entry(digest) {
            Occupied(entry) => {
                let (executable_inode, non_executable_inode) = *entry.get();
                Ok(Some(if is_executable {
                    executable_inode
                } else {
                    non_executable_inode
                }))
            }
            Vacant(entry) => {
                let store = self.store.clone();
                match self
                    .runtime
                    .block_on(async move { store.load_file_bytes_with(digest, |_| ()).await })
                {
                    Ok(()) => {
                        let executable_inode = self.next_inode;
                        self.next_inode += 1;
                        let non_executable_inode = self.next_inode;
                        self.next_inode += 1;
                        entry.insert((executable_inode, non_executable_inode));
                        self.inode_digest_cache.insert(
                            executable_inode,
                            InodeDetails {
                                digest: digest,
                                entry_type: EntryType::File,
                                is_executable: true,
                            },
                        );
                        self.inode_digest_cache.insert(
                            non_executable_inode,
                            InodeDetails {
                                digest: digest,
                                entry_type: EntryType::File,
                                is_executable: false,
                            },
                        );
                        Ok(Some(if is_executable {
                            executable_inode
                        } else {
                            non_executable_inode
                        }))
                    }
                    Err(StoreError::MissingDigest { .. }) => Ok(None),
                    Err(err) => Err(err.to_string()),
                }
            }
        }
    }

    pub fn inode_for_directory(&mut self, digest: Digest) -> Result<Option<Inode>, String> {
        match self.directory_inode_cache.entry(digest) {
            Occupied(entry) => Ok(Some(*entry.get())),
            Vacant(entry) => {
                let store = self.store.clone();
                match self
                    .runtime
                    .block_on(async move { store.load_directory(digest).await })
                {
                    Ok(_) => {
                        // TODO: Kick off some background futures to pre-load the contents of this Directory into
                        // an in-memory cache. Keep a background CPU pool driving those Futures.
                        let inode = self.next_inode;
                        self.next_inode += 1;
                        entry.insert(inode);
                        self.inode_digest_cache.insert(
                            inode,
                            InodeDetails {
                                digest: digest,
                                entry_type: EntryType::Directory,
                                is_executable: true,
                            },
                        );
                        Ok(Some(inode))
                    }
                    Err(StoreError::MissingDigest { .. }) => Ok(None),
                    Err(err) => Err(err.to_string()),
                }
            }
        }
    }

    pub fn file_attr_for(&mut self, inode: Inode) -> Option<fuser::FileAttr> {
        self.inode_digest_cache.get(&inode).map(|f| {
            attr_for(
                inode,
                f.digest.size_bytes as u64,
                fuser::FileType::RegularFile,
                if f.is_executable { 0o555 } else { 0o444 },
            )
        })
    }

    pub fn dir_attr_for(&mut self, digest: Digest) -> Result<fuser::FileAttr, i32> {
        match self.inode_for_directory(digest) {
            Ok(Some(inode)) => Ok(dir_attr_for(inode)),
            Ok(None) => Err(libc::ENOENT),
            Err(err) => {
                error!("Error getting directory for digest {:?}: {}", digest, err);
                Err(libc::EINVAL)
            }
        }
    }

    pub fn readdir_entries(&mut self, inode: Inode) -> Result<Vec<ReaddirEntry>, i32> {
        match inode {
            ROOT => Ok(vec![
                ReaddirEntry {
                    inode: ROOT,
                    kind: fuser::FileType::Directory,
                    name: OsString::from("."),
                },
                ReaddirEntry {
                    inode: ROOT,
                    kind: fuser::FileType::Directory,
                    name: OsString::from(".."),
                },
                ReaddirEntry {
                    inode: DIGEST_ROOT,
                    kind: fuser::FileType::Directory,
                    name: OsString::from("digest"),
                },
                ReaddirEntry {
                    inode: DIRECTORY_ROOT,
                    kind: fuser::FileType::Directory,
                    name: OsString::from("directory"),
                },
            ]),
            // readdir on /digest or /directory will return an empty set.
            // readdir on /directory/abc123... will properly list the contents of that Directory.
            //
            // We skip directory listing for the roots because they will just be very long lists of
            // digests. The only other behaviours we could reasonable use are:
            //  1. Enumerate the entire contents of the local Store (which will be large), ignoring the
            //     remote Store (so the directory listing will still be incomplete - stuff which can be
            //     getattr'd/open'd will still not be present in the directory listing).
            //  2. Store a cache of requests we've successfully served, and claim that the directory
            //     contains exactly those files/directories.
            // All three of these end up with the same problem that readdir doesn't show things which, if
            // you were to getattr/open would actually exist. So we choose the cheapest, and most
            // consistent one: readdir is always empty.
            DIGEST_ROOT | DIRECTORY_ROOT => Ok(vec![]),
            inode => match self.inode_digest_cache.get(&inode) {
                Some(&InodeDetails {
                    digest,
                    entry_type: EntryType::Directory,
                    ..
                }) => {
                    let store = self.store.clone();
                    let maybe_directory = self
                        .runtime
                        .block_on(async move { store.load_directory(digest).await });

                    match maybe_directory {
                        Ok(directory) => {
                            let mut entries = vec![
                                ReaddirEntry {
                                    inode: inode,
                                    kind: fuser::FileType::Directory,
                                    name: OsString::from("."),
                                },
                                ReaddirEntry {
                                    inode: DIRECTORY_ROOT,
                                    kind: fuser::FileType::Directory,
                                    name: OsString::from(".."),
                                },
                            ];

                            let directories = directory.directories.iter().map(|directory| {
                                (
                                    directory.digest.clone(),
                                    directory.name.clone(),
                                    fuser::FileType::Directory,
                                    true,
                                )
                            });
                            let files = directory.files.iter().map(|file| {
                                (
                                    file.digest.clone(),
                                    file.name.clone(),
                                    fuser::FileType::RegularFile,
                                    file.is_executable,
                                )
                            });

                            for (digest, name, filetype, is_executable) in directories.chain(files)
                            {
                                let child_digest =
                                    require_digest(digest.as_ref()).map_err(|err| {
                                        error!("Error parsing digest: {:?}", err);
                                        libc::ENOENT
                                    })?;
                                let maybe_child_inode = match filetype {
                                    fuser::FileType::Directory => {
                                        self.inode_for_directory(child_digest)
                                    }
                                    fuser::FileType::RegularFile => {
                                        self.inode_for_file(child_digest, is_executable)
                                    }
                                    _ => unreachable!(),
                                };
                                match maybe_child_inode {
                                    Ok(Some(child_inode)) => {
                                        entries.push(ReaddirEntry {
                                            inode: child_inode,
                                            kind: filetype,
                                            name: OsString::from(name),
                                        });
                                    }
                                    Ok(None) => {
                                        return Err(libc::ENOENT);
                                    }
                                    Err(err) => {
                                        error!(
                                            "Error reading child directory {:?}: {}",
                                            child_digest, err
                                        );
                                        return Err(libc::EINVAL);
                                    }
                                }
                            }

                            Ok(entries)
                        }
                        Err(StoreError::MissingDigest { .. }) => Err(libc::ENOENT),
                        Err(err) => {
                            error!("Error loading directory {:?}: {}", digest, err);
                            Err(libc::EINVAL)
                        }
                    }
                }
                _ => Err(libc::ENOENT),
            },
        }
    }
}

// inodes:
//  1: /
//  2: /digest
//  3: /directory
//  ... created on demand and cached for the lifetime of the program.
impl fuser::Filesystem for BuildResultFS {
    fn init(
        &mut self,
        _req: &fuser::Request,
        _config: &mut fuser::KernelConfig,
    ) -> Result<(), libc::c_int> {
        self.sender.send(BRFSEvent::Init).map_err(|_| 1)
    }

    fn destroy(&mut self) {
        self.sender
            .send(BRFSEvent::Destroy)
            .unwrap_or_else(|err| warn!("Failed to send {:?} event: {}", BRFSEvent::Destroy, err))
    }

    // Used to answer stat calls
    fn lookup(
        &mut self,
        _req: &fuser::Request<'_>,
        parent: Inode,
        name: &OsStr,
        reply: fuser::ReplyEntry,
    ) {
        let runtime = self.runtime.clone();
        runtime.enter(|| {
            let r = match (parent, name.to_str()) {
                (ROOT, Some("digest")) => Ok(dir_attr_for(DIGEST_ROOT)),
                (ROOT, Some("directory")) => Ok(dir_attr_for(DIRECTORY_ROOT)),
                (DIGEST_ROOT, Some(digest_str)) => match digest_from_filepath(digest_str) {
                    Ok(digest) => self
                        .inode_for_file(digest, true)
                        .map_err(|err| {
                            error!("Error loading file by digest {}: {}", digest_str, err);
                            libc::EINVAL
                        })
                        .and_then(|maybe_inode| {
                            maybe_inode
                                .and_then(|inode| self.file_attr_for(inode))
                                .ok_or(libc::ENOENT)
                        }),
                    Err(err) => {
                        warn!("Invalid digest for file in digest root: {}", err);
                        Err(libc::ENOENT)
                    }
                },
                (DIRECTORY_ROOT, Some(digest_str)) => match digest_from_filepath(digest_str) {
                    Ok(digest) => self.dir_attr_for(digest),
                    Err(err) => {
                        warn!("Invalid digest for directory in directory root: {}", err);
                        Err(libc::ENOENT)
                    }
                },
                (parent, Some(filename)) => {
                    let maybe_cache_entry = self
                        .inode_digest_cache
                        .get(&parent)
                        .cloned()
                        .ok_or(libc::ENOENT);
                    maybe_cache_entry
                        .and_then(|cache_entry| {
                            let store = self.store.clone();
                            let parent_digest = cache_entry.digest;
                            let directory = self
                                .runtime
                                .block_on(async move { store.load_directory(parent_digest).await })
                                .map_err(|err| match err {
                                    StoreError::MissingDigest { .. } => libc::ENOENT,
                                    err => {
                                        error!(
                                            "Error reading directory {:?}: {}",
                                            parent_digest, err
                                        );
                                        libc::EINVAL
                                    }
                                })?;
                            self.node_for_digest(&directory, filename)
                                .ok_or(libc::ENOENT)
                        })
                        .and_then(|node| match node {
                            Node::Directory(directory_node) => {
                                let digest = require_digest(directory_node.digest.as_ref())
                                    .map_err(|err| {
                                        error!("Error parsing digest: {:?}", err);
                                        libc::ENOENT
                                    })?;
                                self.dir_attr_for(digest)
                            }
                            Node::File(file_node) => {
                                let digest =
                                    require_digest(file_node.digest.as_ref()).map_err(|err| {
                                        error!("Error parsing digest: {:?}", err);
                                        libc::ENOENT
                                    })?;
                                self.inode_for_file(digest, file_node.is_executable)
                                    .map_err(|err| {
                                        error!(
                                            "Error loading file by digest {}: {}",
                                            filename, err
                                        );
                                        libc::EINVAL
                                    })
                                    .and_then(|maybe_inode| {
                                        maybe_inode
                                            .and_then(|inode| self.file_attr_for(inode))
                                            .ok_or(libc::ENOENT)
                                    })
                            }
                        })
                }
                _ => Err(libc::ENOENT),
            };
            match r {
                Ok(r) => reply.entry(&TTL, &r, 1),
                Err(err) => reply.error(err),
            }
        })
    }

    fn getattr(&mut self, _req: &fuser::Request<'_>, inode: Inode, reply: fuser::ReplyAttr) {
        let runtime = self.runtime.clone();
        runtime.enter(|| match inode {
            ROOT => reply.attr(&TTL, &dir_attr_for(ROOT)),
            DIGEST_ROOT => reply.attr(&TTL, &dir_attr_for(DIGEST_ROOT)),
            DIRECTORY_ROOT => reply.attr(&TTL, &dir_attr_for(DIRECTORY_ROOT)),
            _ => match self.inode_digest_cache.get(&inode) {
                Some(&InodeDetails {
                    entry_type: EntryType::File,
                    ..
                }) => match self.file_attr_for(inode) {
                    Some(file_attr) => reply.attr(&TTL, &file_attr),
                    None => reply.error(libc::ENOENT),
                },
                Some(&InodeDetails {
                    entry_type: EntryType::Directory,
                    ..
                }) => reply.attr(&TTL, &dir_attr_for(inode)),
                _ => reply.error(libc::ENOENT),
            },
        })
    }

    // TODO: Find out whether fh is ever passed if open isn't explicitly implemented (and whether offset is ever negative)
    fn read(
        &mut self,
        _req: &fuser::Request<'_>,
        inode: Inode,
        _fh: u64,
        offset: i64,
        size: u32,
        _flags: i32,
        _lock_owner: Option<u64>,
        reply: fuser::ReplyData,
    ) {
        let runtime = self.runtime.clone();
        runtime.enter(|| {
            match self.inode_digest_cache.get(&inode) {
                Some(&InodeDetails {
                    digest,
                    entry_type: EntryType::File,
                    ..
                }) => {
                    let reply = Arc::new(Mutex::new(Some(reply)));
                    let reply2 = reply.clone();
                    // TODO: Read from a cache of Futures driven from a CPU pool, so we can merge in-flight
                    // requests, rather than reading from the store directly here.
                    let store = self.store.clone();
                    let result: Result<(), ()> = self
                        .runtime
                        .block_on(async move {
                            store
                                .load_file_bytes_with(digest, move |bytes| {
                                    let begin = std::cmp::min(offset as usize, bytes.len());
                                    let end =
                                        std::cmp::min(offset as usize + size as usize, bytes.len());
                                    let mut reply = reply.lock();
                                    reply.take().unwrap().data(&bytes[begin..end]);
                                })
                                .await
                        })
                        .or_else(|err| {
                            let maybe_reply = reply2.lock().take();
                            match err {
                                StoreError::MissingDigest { .. } => {
                                    if let Some(reply) = maybe_reply {
                                        reply.error(libc::ENOENT);
                                    }
                                }
                                err => {
                                    error!("Error loading bytes for {:?}: {}", digest, err);
                                    if let Some(reply) = maybe_reply {
                                        reply.error(libc::EINVAL);
                                    }
                                }
                            }
                            Ok(())
                        });
                    result.expect(
                        "Error from read future which should have been handled in the future ",
                    );
                }
                _ => reply.error(libc::ENOENT),
            }
        })
    }

    fn readdir(
        &mut self,
        _req: &fuser::Request<'_>,
        inode: Inode,
        // TODO: Find out whether fh is ever passed if open isn't explicitly implemented (and whether offset is ever negative)
        _fh: u64,
        offset: i64,
        mut reply: fuser::ReplyDirectory,
    ) {
        let runtime = self.runtime.clone();
        runtime.enter(|| {
            match self.readdir_entries(inode) {
                Ok(entries) => {
                    // 0 is a magic offset which means no offset, whereas a non-zero offset means start
                    // _after_ that entry. Inconsistency is fun.
                    let to_skip = if offset == 0 { 0 } else { offset + 1 } as usize;
                    let mut i = offset;
                    for entry in entries.into_iter().skip(to_skip) {
                        if reply.add(entry.inode, i, entry.kind, entry.name) {
                            // Buffer is full, don't add more entries.
                            break;
                        }
                        i += 1;
                    }
                    reply.ok();
                }
                Err(err) => reply.error(err),
            }
        })
    }

    // If this isn't implemented, OSX will try to manipulate ._ files to manage xattrs out of band, which adds both overhead and logspam.
    fn listxattr(
        &mut self,
        _req: &fuser::Request<'_>,
        _inode: Inode,
        _size: u32,
        reply: fuser::ReplyXattr,
    ) {
        let runtime = self.runtime.clone();
        runtime.enter(|| {
            reply.size(0);
        })
    }
}

pub fn mount<P: AsRef<Path>>(
    mount_path: P,
    store: Store,
    runtime: task_executor::Executor,
) -> std::io::Result<(fuser::BackgroundSession, Receiver<BRFSEvent>)> {
    // TODO: Work out how to disable caching in the filesystem
    let options = vec![
        fuser::MountOption::RO,
        fuser::MountOption::FSName("brfs".to_owned()),
        fuser::MountOption::CUSTOM("noapplexattr".to_owned()),
    ];

    let (sender, receiver) = channel();
    let brfs = BuildResultFS::new(sender, runtime, store);

    debug!("About to spawn_mount with options {:?}", options);
    let result = fuser::spawn_mount2(brfs, &mount_path, &options);
    // N.B.: The session won't be used by the caller, but we return it since a reference must be
    // maintained to prevent early dropping which unmounts the filesystem.
    result.map(|session| (session, receiver))
}

#[tokio::main]
async fn main() {
    env_logger::init();

    let default_store_path = Store::default_path();

    let args = Command::new("brfs")
    .arg(
      Arg::new("local-store-path")
        .takes_value(true)
        .long("local-store-path")
        .default_value_os(default_store_path.as_ref())
        .required(false),
    ).arg(
      Arg::new("server-address")
        .takes_value(true)
        .long("server-address")
        .required(false),
    ).arg(
      Arg::new("remote-instance-name")
        .takes_value(true)
        .long("remote-instance-name")
        .required(false),
    ).arg(
      Arg::new("root-ca-cert-file")
        .help("Path to file containing root certificate authority certificates. If not set, TLS will not be used when connecting to the remote.")
        .takes_value(true)
        .long("root-ca-cert-file")
        .required(false)
    ).arg(
      Arg::new("oauth-bearer-token-file")
        .help("Path to file containing oauth bearer token. If not set, no authorization will be provided to remote servers.")
        .takes_value(true)
        .long("oauth-bearer-token-file")
        .required(false)
    ).arg(
      Arg::new("mount-path")
        .required(true)
        .takes_value(true),
    )
    .arg(
      Arg::new("rpc-concurrency-limit")
          .help("Maximum concurrenct RPCs to the service.")
          .takes_value(true)
          .long("rpc-concurrency-limit")
          .required(false)
          .default_value("128")
    ).arg(
    Arg::new("batch-api-size-limit")
        .help("Maximum total size of blobs allowed to be sent in a single batch API call to the remote store.")
        .takes_value(true)
        .long("batch-api-size-limit")
        .required(false)
        .default_value("4194304")
  )
      .get_matches();

    let mount_path = args.value_of("mount-path").unwrap();
    let store_path = args.value_of("local-store-path").unwrap();

    let root_ca_certs = args
        .value_of("root-ca-cert-file")
        .map(|path| std::fs::read(path).expect("Error reading root CA certs file"));

    let mut headers = BTreeMap::new();
    if let Some(oauth_path) = args.value_of("oauth-bearer-token-file") {
        let token = match std::fs::read_to_string(oauth_path) {
            Ok(token) => token,
            Err(err) => {
                error!(
                    "Error reading oauth bearer token from {:?}: {}",
                    oauth_path, err
                );
                std::process::exit(1);
            }
        };
        headers.insert(
            "authorization".to_owned(),
            format!("Bearer {}", token.trim()),
        );
    }

    let runtime = task_executor::Executor::new();

    let tls_config = match tls::Config::new(root_ca_certs, None) {
        Ok(tls_config) => tls_config,
        Err(err) => {
            error!("Error when creating TLS configuration: {err:?}");
            std::process::exit(1);
        }
    };

    let local_only_store =
        Store::local_only(runtime.clone(), store_path).expect("Error making local store.");
    let store = match args.value_of("server-address") {
        Some(address) => local_only_store
            .into_with_remote(RemoteStoreOptions {
                cas_address: address.to_owned(),
                instance_name: args.value_of("remote-instance-name").map(str::to_owned),
                tls_config,
                headers,
                chunk_size_bytes: 4 * 1024 * 1024,
                rpc_timeout: std::time::Duration::from_secs(5 * 60),
                rpc_retries: 1,
                rpc_concurrency_limit: args
                    .value_of_t::<usize>("rpc-concurrency-limit")
                    .expect("Bad rpc-concurrency-limit flag"),
                batch_api_size_limit: args
                    .value_of_t::<usize>("batch-api-size-limit")
                    .expect("Bad batch-api-size-limit flag"),
            })
            .await
            .expect("Error making remote store"),
        None => local_only_store,
    };

    #[derive(Clone, Copy, Debug)]
    enum Sig {
        Int,
        Term,
        Unmount,
    }

    fn install_handler<F>(install_fn: F, sig: Sig) -> impl StreamExt<Item = Option<Sig>>
    where
        F: Fn() -> SignalKind,
    {
        SignalStream::new(
            signal(install_fn()).unwrap_or_else(|_| panic!("Failed to install SIG{sig:?} handler")),
        )
        .map(move |_| Some(sig))
    }

    let sigint = install_handler(SignalKind::interrupt, Sig::Int);
    let sigterm = install_handler(SignalKind::terminate, Sig::Term);

    match mount(mount_path, store, runtime.clone()) {
        Err(err) => {
            error!(
                "Store {} failed to mount at {}: {}",
                store_path, mount_path, err
            );
            std::process::exit(1);
        }
        Ok((_, receiver)) => {
            match receiver.recv().unwrap() {
                BRFSEvent::Init => debug!("Store {} mounted at {}", store_path, mount_path),
                BRFSEvent::Destroy => {
                    warn!("Externally unmounted before we could mount.");
                    return;
                }
            }

            let unmount = task::spawn_blocking(move || {
                // N.B.: In practice recv always errs and we exercise the or branch. It seems the sender
                // side thread always exits (which drops our BuildResultFS) before we get a chance to
                // complete the read.
                match receiver.recv().unwrap_or(BRFSEvent::Destroy) {
                    BRFSEvent::Destroy => Some(Sig::Unmount),
                    event => {
                        warn!("Received unexpected event {:?}", event);
                        None
                    }
                }
            })
            .map(|res| res.unwrap())
            .into_stream();

            let mut shutdown_signal = sigint.merge(sigterm).merge(unmount).filter_map(|x| x);
            debug!("Awaiting shutdown signal ...");
            if let Some(sig) = shutdown_signal.next().await {
                match sig {
                    Sig::Unmount => debug!("Externally unmounted"),
                    sig => debug!("Received SIG{:?}", sig),
                }
            }
        }
    }
}

#[cfg(test)]
mod tests;

#[cfg(test)]
mod syscall_tests;
