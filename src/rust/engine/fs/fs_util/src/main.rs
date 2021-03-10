// Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
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
#![type_length_limit = "1881109"]

use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::exit;
use std::sync::Arc;
use std::time::Duration;

use bazel_protos::require_digest;
use bytes::Bytes;
use clap::{value_t, App, Arg, SubCommand};
use fs::{
  GlobExpansionConjunction, GlobMatching, PreparedPathGlobs, RelativePath, StrictGlobMatching,
};
use futures::future::{self, BoxFuture};
use futures::FutureExt;
use grpc_util::prost::MessageExt;
use hashing::{Digest, Fingerprint};
use parking_lot::Mutex;
use serde_derive::Serialize;
use std::collections::BTreeMap;
use store::{
  Snapshot, SnapshotOps, SnapshotOpsError, Store, StoreFileByDigest, SubsetParams, UploadSummary,
};

#[derive(Debug)]
enum ExitCode {
  UnknownError = 1,
  NotFound = 2,
}

#[derive(Debug)]
struct ExitError(String, ExitCode);

impl From<String> for ExitError {
  fn from(s: String) -> Self {
    ExitError(s, ExitCode::UnknownError)
  }
}

#[derive(Serialize)]
struct SummaryWithDigest {
  digest: Digest,
  summary: Option<UploadSummary>,
}

#[tokio::main]
async fn main() {
  env_logger::init();

  match execute(
    &App::new("fs_util")
      .subcommand(
        SubCommand::with_name("file")
          .subcommand(
            SubCommand::with_name("cat")
              .about("Output the contents of a file by fingerprint.")
              .arg(Arg::with_name("fingerprint").required(true).takes_value(
                true,
              ))
              .arg(Arg::with_name("size_bytes").required(true).takes_value(
                true,
              )),
          )
          .subcommand(
            SubCommand::with_name("save")
              .about(
                "Ingest a file by path, which allows it to be used in Directories/Snapshots. \
Outputs a fingerprint of its contents and its size in bytes, separated by a space.",
              )
              .arg(Arg::with_name("path").required(true).takes_value(true))
              .arg(Arg::with_name("output-mode").long("output-mode").possible_values(&["json", "simple"]).default_value("simple").multiple(false).takes_value(true).help(
                "Set to manipulate the way a report is displayed."
              )),
          ),
      )
      .subcommand(
        SubCommand::with_name("directory")
          .subcommand(
            SubCommand::with_name("materialize")
              .about(
                "Materialize a directory by fingerprint to the filesystem. \
Destination must not exist before this command is run.",
              )
              .arg(Arg::with_name("fingerprint").required(true).takes_value(
                true,
              ))
              .arg(Arg::with_name("size_bytes").required(true).takes_value(
                true,
              ))
              .arg(Arg::with_name("destination").required(true).takes_value(
                true,
              )),
          )
          .subcommand(
            SubCommand::with_name("save")
              .about(
                "Ingest a directory recursively. Saves all files found therein and saves Directory \
protos for each directory found. Outputs a fingerprint of the canonical top-level Directory proto \
and the size of the serialized proto in bytes, separated by a space.",
              )
              .arg(
                Arg::with_name("globs")
                  .required(true)
                  .takes_value(true)
                  .multiple(true)
                  .help(
                    "globs matching the files and directories which should be included in the \
directory, relative to the root.",
                  ),
              )
                .arg(Arg::with_name("root").long("root").required(true).takes_value(true).help(
                  "Root under which the globs live. The Directory proto produced will be relative \
to this directory.",
            ))
                .arg(Arg::with_name("output-mode").long("output-mode").possible_values(&["json", "simple"]).default_value("simple").multiple(false).takes_value(true).help(
                  "Set to manipulate the way a report is displayed."
                )),
          )
          .subcommand(
            SubCommand::with_name("cat-proto")
              .about(
                "Output the bytes of a serialized Directory proto addressed by fingerprint.",
              )
              .arg(
                Arg::with_name("output-format")
                  .long("output-format")
                  .takes_value(true)
                  .default_value("binary")
                  .possible_values(&["binary", "recursive-file-list", "recursive-file-list-with-digests", "text"]),
              )
              .arg(
                Arg::with_name("child-dir")
                    .long("child-dir")
                    .takes_value(true)
                    .help("Relative path of child Directory inside the Directory represented by the digest to navigate to before operating.")
              )
              .arg(Arg::with_name("fingerprint").required(true).takes_value(
                true,
              ))
              .arg(Arg::with_name("size_bytes").required(true).takes_value(
                true,
              )),
          ),
      )
      .subcommand(
        SubCommand::with_name("cat")
          .about(
            "Output the contents of a file or Directory proto addressed by fingerprint.",
          )
          .arg(Arg::with_name("fingerprint").required(true).takes_value(
            true,
          ))
          .arg(Arg::with_name("size_bytes").required(true).takes_value(
            true,
          )),
      )
        .subcommand(
          SubCommand::with_name("directories")
              .subcommand(SubCommand::with_name("list"))
              .about("List all directory digests known in the local store")
        )
        .subcommand(
          SubCommand::with_name("gc")
              .about("Garbage collect the on-disk store. Note that after running this command, any processes with an open store (e.g. a pantsd) may need to re-initialize their store.")
              .arg(
                Arg::with_name("target-size-bytes")
                    .takes_value(true)
                    .long("target-size-bytes")
                    .required(true),
              )
        )
      .arg(
        Arg::with_name("local-store-path")
          .takes_value(true)
          .long("local-store-path")
          .required(false),
      )
        .arg(
          Arg::with_name("server-address")
              .takes_value(true)
              .long("server-address")
              .required(false)
        )
        .arg(
          Arg::with_name("root-ca-cert-file")
              .help("Path to file containing root certificate authority certificates. If not set, TLS will not be used when connecting to the remote.")
              .takes_value(true)
              .long("root-ca-cert-file")
              .required(false)
        )
        .arg(
          Arg::with_name("oauth-bearer-token-file")
              .help("Path to file containing oauth bearer token. If not set, no authorization will be provided to remote servers.")
              .takes_value(true)
              .long("oauth-bearer-token-file")
              .required(false)
        )
        .arg(Arg::with_name("remote-instance-name")
            .takes_value(true)
                 .long("remote-instance-name")
                 .required(false))
        .arg(
          Arg::with_name("chunk-bytes")
              .help("Number of bytes to include per-chunk when uploading bytes. grpc imposes a hard message-size limit of around 4MB.")
              .takes_value(true)
              .long("chunk-bytes")
              .required(false)
              .default_value(&format!("{}", 3 * 1024 * 1024))
        )
        .arg(
          Arg::with_name("rpc-attempts")
              .help("Number of times to attempt any RPC before giving up.")
              .takes_value(true)
              .long("rpc-attempts")
              .required(false)
              .default_value("3")
        )
      .get_matches(),
  ).await {
    Ok(_) => {}
    Err(err) => {
      eprintln!("{}", err.0);
      exit(err.1 as i32)
    }
  };
}

// TODO: Sure, it's a bit long...
#[allow(clippy::cognitive_complexity)]
async fn execute(top_match: &clap::ArgMatches<'_>) -> Result<(), ExitError> {
  let store_dir = top_match
    .value_of("local-store-path")
    .map(PathBuf::from)
    .unwrap_or_else(Store::default_path);
  let runtime = task_executor::Executor::new();
  let (store, store_has_remote) = {
    let (store_result, store_has_remote) = match top_match.value_of("server-address") {
      Some(cas_address) => {
        let chunk_size =
          value_t!(top_match.value_of("chunk-bytes"), usize).expect("Bad chunk-bytes flag");

        let root_ca_certs = if let Some(path) = top_match.value_of("root-ca-cert-file") {
          Some(
            std::fs::read(path)
              .map_err(|err| format!("Error reading root CA certs file {}: {}", path, err))?,
          )
        } else {
          None
        };

        let mut headers = BTreeMap::new();
        if let Some(oauth_path) = top_match.value_of("oauth-bearer-token-file") {
          let token = std::fs::read_to_string(oauth_path).map_err(|err| {
            format!(
              "Error reading oauth bearer token from {:?}: {}",
              oauth_path, err
            )
          })?;
          headers.insert(
            "authorization".to_owned(),
            format!("Bearer {}", token.trim()),
          );
        }

        (
          Store::with_remote(
            runtime.clone(),
            &store_dir,
            cas_address,
            top_match
              .value_of("remote-instance-name")
              .map(str::to_owned),
            root_ca_certs,
            headers,
            chunk_size,
            // This deadline is really only in place because otherwise DNS failures
            // leave this hanging forever.
            //
            // Make fs_util have a very long deadline (because it's not configurable,
            // like it is inside pants) until we switch to Tower (where we can more
            // carefully control specific components of timeouts).
            //
            // See https://github.com/pantsbuild/pants/pull/6433 for more context.
            Duration::from_secs(30 * 60),
            value_t!(top_match.value_of("rpc-attempts"), usize).expect("Bad rpc-attempts flag"),
          ),
          true,
        )
      }
      None => (Store::local_only(runtime.clone(), &store_dir), false),
    };
    let store = store_result.map_err(|e| {
      format!(
        "Failed to open/create store for directory {:?}: {}",
        store_dir, e
      )
    })?;
    (store, store_has_remote)
  };

  match top_match.subcommand() {
    ("file", Some(sub_match)) => {
      match sub_match.subcommand() {
        ("cat", Some(args)) => {
          let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
          let size_bytes = args
            .value_of("size_bytes")
            .unwrap()
            .parse::<usize>()
            .expect("size_bytes must be a non-negative number");
          let digest = Digest::new(fingerprint, size_bytes);
          let write_result = store
            .load_file_bytes_with(digest, |bytes| io::stdout().write_all(&bytes).unwrap())
            .await?;
          write_result
            .ok_or_else(|| {
              ExitError(
                format!("File with digest {:?} not found", digest),
                ExitCode::NotFound,
              )
            })
            .map(|((), _metadata)| ())
        }
        ("save", Some(args)) => {
          let path = PathBuf::from(args.value_of("path").unwrap());
          // Canonicalize path to guarantee that a relative path has a parent.
          let posix_fs = make_posix_fs(
            runtime.clone(),
            path
              .canonicalize()
              .map_err(|e| format!("Error canonicalizing path {:?}: {:?}", path, e))?
              .parent()
              .ok_or_else(|| format!("File being saved must have parent but {:?} did not", path))?,
          );
          let file = posix_fs
            .stat_sync(PathBuf::from(path.file_name().unwrap()))
            .unwrap()
            .ok_or_else(|| format!("Tried to save file {:?} but it did not exist", path))?;
          match file {
            fs::Stat::File(f) => {
              let digest = store::OneOffStoreFileByDigest::new(store.clone(), Arc::new(posix_fs))
                .store_by_digest(f)
                .await
                .unwrap();

              let report = ensure_uploaded_to_remote(&store, store_has_remote, digest)
                .await
                .unwrap();
              print_upload_summary(args.value_of("output-mode"), &report);

              Ok(())
            }
            o => Err(
              format!(
                "Tried to save file {:?} but it was not a file, was a {:?}",
                path, o
              )
              .into(),
            ),
          }
        }
        (_, _) => unimplemented!(),
      }
    }
    ("directory", Some(sub_match)) => match sub_match.subcommand() {
      ("materialize", Some(args)) => {
        let destination = PathBuf::from(args.value_of("destination").unwrap());
        let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
        let size_bytes = args
          .value_of("size_bytes")
          .unwrap()
          .parse::<usize>()
          .expect("size_bytes must be a non-negative number");
        let digest = Digest::new(fingerprint, size_bytes);
        store
          .materialize_directory(destination, digest)
          .await
          .map(|metadata| {
            eprintln!("{}", serde_json::to_string_pretty(&metadata).unwrap());
          })
          .map_err(|err| {
            if err.contains("not found") {
              ExitError(err, ExitCode::NotFound)
            } else {
              err.into()
            }
          })
      }
      ("save", Some(args)) => {
        let posix_fs = Arc::new(make_posix_fs(
          runtime.clone(),
          args.value_of("root").unwrap(),
        ));
        let store_copy = store.clone();
        let paths = posix_fs
          .expand_globs(
            fs::PathGlobs::new(
              args
                .values_of("globs")
                .unwrap()
                .map(str::to_string)
                .collect::<Vec<String>>(),
              // By using `Ignore`, we say that we don't care if some globs fail to expand. Is
              // that a valid assumption?
              fs::StrictGlobMatching::Ignore,
              fs::GlobExpansionConjunction::AllMatch,
            )
            .parse()?,
          )
          .await
          .map_err(|e| format!("Error expanding globs: {:?}", e))?;

        let snapshot = Snapshot::from_path_stats(
          store_copy.clone(),
          store::OneOffStoreFileByDigest::new(store_copy, posix_fs),
          paths,
        )
        .await?;

        let report = ensure_uploaded_to_remote(&store, store_has_remote, snapshot.digest).await?;
        print_upload_summary(args.value_of("output-mode"), &report);

        Ok(())
      }
      ("cat-proto", Some(args)) => {
        let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
        let size_bytes = args
          .value_of("size_bytes")
          .unwrap()
          .parse::<usize>()
          .expect("size_bytes must be a non-negative number");
        let mut digest = Digest::new(fingerprint, size_bytes);

        if let Some(prefix_to_strip) = args.value_of("child-dir") {
          let mut result = store
            .subset(
              digest,
              SubsetParams {
                globs: PreparedPathGlobs::create(
                  vec![format!("{}/**", prefix_to_strip)],
                  StrictGlobMatching::Ignore,
                  GlobExpansionConjunction::AnyMatch,
                )?,
              },
            )
            .await;
          // It's a shame we can't just .and_then here, because we can't use async closures.
          if let Ok(subset_digest) = result {
            result = store
              .strip_prefix(subset_digest, RelativePath::new(prefix_to_strip)?)
              .await;
          }
          digest = result.map_err(|err| match err {
            SnapshotOpsError::String(string)
            | SnapshotOpsError::DigestMergeFailure(string)
            | SnapshotOpsError::GlobMatchError(string) => string,
          })?
        }

        let proto_bytes: Option<Vec<u8>> = match args.value_of("output-format").unwrap() {
          "binary" => {
            let maybe_directory = store.load_directory(digest).await?;
            maybe_directory.map(|(d, _metadata)| d.to_bytes().to_vec())
          }
          "text" => {
            let maybe_p = store.load_directory(digest).await?;
            maybe_p.map(|(p, _metadata)| format!("{:?}\n", p).as_bytes().to_vec())
          }
          "recursive-file-list" => {
            let maybe_v = expand_files(store, digest).await?;
            maybe_v
              .map(|v| {
                v.into_iter()
                  .map(|(name, _digest)| format!("{}\n", name))
                  .collect::<Vec<String>>()
                  .join("")
              })
              .map(String::into_bytes)
          }
          "recursive-file-list-with-digests" => {
            let maybe_v = expand_files(store, digest).await?;
            maybe_v
              .map(|v| {
                v.into_iter()
                  .map(|(name, digest)| format!("{} {} {}\n", name, digest.hash, digest.size_bytes))
                  .collect::<Vec<String>>()
                  .join("")
              })
              .map(String::into_bytes)
          }
          format => {
            return Err(format!("Unexpected value of --output-format arg: {}", format).into())
          }
        };
        match proto_bytes {
          Some(bytes) => {
            io::stdout().write_all(&bytes).unwrap();
            Ok(())
          }
          None => Err(ExitError(
            format!("Directory with digest {:?} not found", digest),
            ExitCode::NotFound,
          )),
        }
      }
      (_, _) => unimplemented!(),
    },
    ("cat", Some(args)) => {
      let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
      let size_bytes = args
        .value_of("size_bytes")
        .unwrap()
        .parse::<usize>()
        .expect("size_bytes must be a non-negative number");
      let digest = Digest::new(fingerprint, size_bytes);
      let v = match store
        .load_file_bytes_with(digest, |bytes| Bytes::copy_from_slice(bytes))
        .await?
      {
        None => {
          let maybe_dir = store.load_directory(digest).await?;
          maybe_dir.map(|(dir, _metadata)| dir.to_bytes())
        }
        Some((bytes, _metadata)) => Some(bytes),
      };
      match v {
        Some(bytes) => {
          io::stdout().write_all(&bytes).unwrap();
          Ok(())
        }
        None => Err(ExitError(
          format!("Digest {:?} not found", digest),
          ExitCode::NotFound,
        )),
      }
    }
    ("directories", Some(sub_match)) => match sub_match.subcommand() {
      ("list", _) => {
        for digest in store
          .all_local_digests(::store::EntryType::Directory)
          .expect("Error opening store")
        {
          println!("{} {}", digest.hash, digest.size_bytes);
        }
        Ok(())
      }
      _ => unimplemented!(),
    },
    ("gc", Some(args)) => {
      let target_size_bytes = value_t!(args.value_of("target-size-bytes"), usize)
        .expect("--target-size-bytes must be passed as a non-negative integer");
      store.garbage_collect(target_size_bytes, store::ShrinkBehavior::Compact)?;
      Ok(())
    }

    (_, _) => unimplemented!(),
  }
}

async fn expand_files(
  store: Store,
  digest: Digest,
) -> Result<Option<Vec<(String, Digest)>>, String> {
  let files = Arc::new(Mutex::new(Vec::new()));
  let vec_opt = expand_files_helper(store, digest, String::new(), files.clone()).await?;
  Ok(vec_opt.map(|_| {
    let mut v = Arc::try_unwrap(files).unwrap().into_inner();
    v.sort_by(|(l, _), (r, _)| l.cmp(r));
    v
  }))
}

fn expand_files_helper(
  store: Store,
  digest: Digest,
  prefix: String,
  files: Arc<Mutex<Vec<(String, Digest)>>>,
) -> BoxFuture<'static, Result<Option<()>, String>> {
  async move {
    let maybe_dir = store.load_directory(digest).await?;
    match maybe_dir {
      Some((dir, _metadata)) => {
        {
          let mut files_unlocked = files.lock();
          for file in &dir.files {
            let file_digest = require_digest(file.digest.as_ref())?;
            files_unlocked.push((format!("{}{}", prefix, file.name), file_digest));
          }
        }
        let subdirs_and_digests = dir
          .directories
          .iter()
          .map(move |subdir| {
            let digest = require_digest(subdir.digest.as_ref());
            digest.map(|digest| (subdir, digest))
          })
          .collect::<Result<Vec<_>, _>>()?;
        future::try_join_all(
          subdirs_and_digests
            .into_iter()
            .map(move |(subdir, digest)| {
              expand_files_helper(
                store.clone(),
                digest,
                format!("{}{}/", prefix, subdir.name),
                files.clone(),
              )
            })
            .collect::<Vec<_>>(),
        )
        .await
        .map(|_| Some(()))
      }
      None => Ok(None),
    }
  }
  .boxed()
}

fn make_posix_fs<P: AsRef<Path>>(executor: task_executor::Executor, root: P) -> fs::PosixFS {
  // Unwrapping the output of creating the git ignorer with no patterns is infallible.
  fs::PosixFS::new(
    &root,
    fs::GitignoreStyleExcludes::create(vec![]).unwrap(),
    executor,
  )
  .unwrap()
}

async fn ensure_uploaded_to_remote(
  store: &Store,
  store_has_remote: bool,
  digest: Digest,
) -> Result<SummaryWithDigest, String> {
  let summary = if store_has_remote {
    store
      .ensure_remote_has_recursive(vec![digest])
      .await
      .map(Some)
  } else {
    Ok(None)
  };
  summary.map(move |summary| SummaryWithDigest { digest, summary })
}

fn print_upload_summary(mode: Option<&str>, report: &SummaryWithDigest) {
  match mode {
    Some("json") => println!("{}", serde_json::to_string_pretty(&report).unwrap()),
    Some("simple") => println!("{} {}", report.digest.hash, report.digest.size_bytes),
    // This should never be reached, as clap should error with unknown formats.
    _ => eprintln!("Unknown summary format."),
  };
}
