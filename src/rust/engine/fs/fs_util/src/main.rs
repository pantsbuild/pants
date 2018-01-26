extern crate bazel_protos;
extern crate boxfuture;
extern crate bytes;
extern crate clap;
extern crate fs;
extern crate futures;
extern crate hashing;
extern crate protobuf;

use boxfuture::{Boxable, BoxFuture};
use bytes::Bytes;
use clap::{App, Arg, SubCommand};
use fs::{GetFileDigest, ResettablePool, Snapshot, Store, VFS};
use futures::future::{self, Future, join_all};
use hashing::{Digest, Fingerprint};
use protobuf::Message;
use std::error::Error;
use std::fs::File;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::exit;
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug)]
enum ExitCode {
  UnknownError = 1,
  NotFound = 2,
}

#[derive(Debug)]
struct ExitError(pub String, pub ExitCode);

impl From<String> for ExitError {
  fn from(s: String) -> Self {
    ExitError(s, ExitCode::UnknownError)
  }
}

fn main() {
  match execute(
    App::new("fs_util")
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
              .arg(Arg::with_name("path").required(true).takes_value(true)),
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
                  .possible_values(&["binary", "text"]),
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
      .arg(
        Arg::with_name("local-store-path")
          .takes_value(true)
          .long("local-store-path")
          .required(true),
      )
        .arg(
          Arg::with_name("server-address")
              .takes_value(true)
              .long("server-address")
              .required(false)
        )
      .get_matches(),
  ) {
    Ok(_) => {}
    Err(err) => {
      eprintln!("{}", err.0);
      exit(err.1 as i32)
    }
  };
}

fn execute(top_match: clap::ArgMatches) -> Result<(), ExitError> {
  let store_dir = top_match.value_of("local-store-path").unwrap();
  let pool = Arc::new(ResettablePool::new("fsutil-pool-".to_string()));
  let (store, store_has_remote) = {
    let (store_result, store_has_remote) = match top_match.value_of("server-address") {
      Some(cas_address) => {
        (
          Store::with_remote(
            store_dir,
            pool.clone(),
            cas_address,
            1,
            10 * 1024 * 1024,
            Duration::from_secs(30),
          ),
          true,
        )
      }
      None => (Store::local_only(store_dir, pool.clone()), false),
    };
    let store = store_result.map_err(|e| {
      format!(
        "Failed to open/create store for directory {}: {}",
        store_dir,
        e
      )
    })?;
    (Arc::new(store), store_has_remote)
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
          let digest = Digest(fingerprint, size_bytes);
          let write_result = store
            .load_file_bytes_with(digest, |bytes| io::stdout().write_all(&bytes).unwrap())
            .wait()?;
          write_result.ok_or_else(|| {
            ExitError(
              format!("File with digest {:?} not found", digest),
              ExitCode::NotFound,
            )
          })
        }
        ("save", Some(args)) => {
          let path = PathBuf::from(args.value_of("path").unwrap());
          // Canonicalize path to guarantee that a relative path has a parent.
          let posix_fs = make_posix_fs(
            path
              .canonicalize()
              .map_err(|e| {
                format!("Error canonicalizing path {:?}: {}", path, e.description())
              })?
              .parent()
              .ok_or_else(|| {
                format!("File being saved must have parent but {:?} did not", path)
              })?,
            pool,
          );
          let file = posix_fs
            .stat(PathBuf::from(path.file_name().unwrap()))
            .unwrap();
          match file {
            fs::Stat::File(f) => {
              let digest = FileSaver {
                store: store.clone(),
                posix_fs: Arc::new(posix_fs),
              }.digest(&f)
                .wait()
                .unwrap();
              if store_has_remote {
                store.ensure_remote_has_recursive(vec![digest]).wait()?;
              }
              Ok(println!("{} {}", digest.0, digest.1))
            }
            o => Err(
              format!(
                "Tried to save file {:?} but it was not a file, was a {:?}",
                path,
                o
              ).into(),
            ),
          }

        }
        (_, _) => unimplemented!(),
      }
    }
    ("directory", Some(sub_match)) => {
      match sub_match.subcommand() {
        ("materialize", Some(args)) => {
          let destination = PathBuf::from(args.value_of("destination").unwrap());
          let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
          let size_bytes = args
            .value_of("size_bytes")
            .unwrap()
            .parse::<usize>()
            .expect("size_bytes must be a non-negative number");
          let digest = Digest(fingerprint, size_bytes);
          materialize_directory(store, destination, digest).wait()
        }
        ("save", Some(args)) => {
          let posix_fs = Arc::new(make_posix_fs(args.value_of("root").unwrap(), pool));
          let store_copy = store.clone();
          let digest = posix_fs
            .expand(fs::PathGlobs::create(
              &args
                .values_of("globs")
                .unwrap()
                .map(|s| s.to_string())
                .collect::<Vec<String>>(),
              &[],
            )?)
            .map_err(|e| format!("Error expanding globs: {}", e.description()))
            .and_then(move |paths| {
              Snapshot::from_path_stats(
                store_copy.clone(),
                Arc::new(FileSaver {
                  store: store_copy,
                  posix_fs: posix_fs,
                }),
                paths,
              )
            })
            .map(|snapshot| snapshot.digest.unwrap())
            .wait()?;
          if store_has_remote {
            store.ensure_remote_has_recursive(vec![digest]).wait()?;
          }
          Ok(println!("{} {}", digest.0, digest.1))
        }
        ("cat-proto", Some(args)) => {
          let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
          let size_bytes = args
            .value_of("size_bytes")
            .unwrap()
            .parse::<usize>()
            .expect("size_bytes must be a non-negative number");
          let digest = Digest(fingerprint, size_bytes);
          let proto_bytes = match args.value_of("output-format").unwrap() {
            "binary" => {
              store.load_directory(digest).wait().map(|maybe_d| {
                maybe_d.map(|d| d.write_to_bytes().unwrap())
              })
            }
            "text" => {
              store.load_directory(digest).wait().map(|maybe_p| {
                maybe_p.map(|p| format!("{:?}\n", p).as_bytes().to_vec())
              })
            }
            format => Err(format!(
              "Unexpected value of --output-format arg: {}",
              format
            )),
          }?;
          match proto_bytes {
            Some(bytes) => {
              io::stdout().write(&bytes).unwrap();
              Ok(())
            }
            None => Err(ExitError(
              format!("Directory with digest {:?} not found", digest),
              ExitCode::NotFound,
            )),
          }
        }
        (_, _) => unimplemented!(),
      }
    }
    ("cat", Some(args)) => {
      let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
      let size_bytes = args
        .value_of("size_bytes")
        .unwrap()
        .parse::<usize>()
        .expect("size_bytes must be a non-negative number");
      let digest = Digest(fingerprint, size_bytes);
      let v = match store.load_file_bytes_with(digest, |bytes| bytes).wait()? {
        None => {
          store
            .load_directory(digest)
            .map(|maybe_dir| {
              maybe_dir.map(|dir| {
                Bytes::from(dir.write_to_bytes().expect(
                  "Error serializing Directory proto",
                ))
              })
            })
            .wait()?
        }
        some => some,
      };
      match v {
        Some(bytes) => {
          io::stdout().write(&bytes).unwrap();
          Ok(())
        }
        None => Err(ExitError(
          format!("Digest {:?} not found", digest),
          ExitCode::NotFound,
        )),
      }
    }

    (_, _) => unimplemented!(),
  }
}

fn make_posix_fs<P: AsRef<Path>>(root: P, pool: Arc<ResettablePool>) -> fs::PosixFS {
  fs::PosixFS::new(&root, pool, vec![]).unwrap()
}

struct FileSaver {
  store: Arc<Store>,
  posix_fs: Arc<fs::PosixFS>,
}

impl GetFileDigest<String> for FileSaver {
  fn digest(&self, file: &fs::File) -> BoxFuture<Digest, String> {
    let file_copy = file.clone();
    let store = self.store.clone();
    self
      .posix_fs
      .read_file(&file)
      .map_err(move |err| {
        format!("Error reading file {:?}: {}", file_copy, err.description())
      })
      .and_then(move |content| store.store_file_bytes(content.content, true))
      .to_boxed()
  }
}

fn materialize_directory(
  store: Arc<Store>,
  destination: PathBuf,
  digest: Digest,
) -> BoxFuture<(), ExitError> {
  let mkdir = make_clean_dir(&destination).map_err(|e| {
    format!(
      "Error making directory {:?}: {:?}",
      destination,
      e,
    ).into()
  });
  match mkdir {
    Ok(()) => {}
    Err(e) => return future::err(e).to_boxed(),
  };
  store
    .load_directory(digest)
    .map_err(|e| e.into())
    .and_then(move |directory_opt| {
      directory_opt.ok_or_else(|| {
        ExitError(
          format!("Directory with digest {:?} not found", digest),
          ExitCode::NotFound,
        )
      })
    })
    .and_then(move |directory| {
      let file_futures = directory
        .get_files()
        .iter()
        .map(|file_node| {
          let store = store.clone();
          let path = destination.join(file_node.get_name());
          let digest: Digest = file_node.get_digest().into();
          materialize_file(store, path, digest)
        })
        .collect::<Vec<_>>();
      let directory_futures = directory
        .get_directories()
        .iter()
        .map(|directory_node| {
          let store = store.clone();
          let path = destination.join(directory_node.get_name());
          let digest: Digest = directory_node.get_digest().into();
          materialize_directory(store, path, digest)
        })
        .collect::<Vec<_>>();
      join_all(file_futures)
        .join(join_all(directory_futures))
        .map(|_| ())
    })
    .to_boxed()
}

fn materialize_file(
  store: Arc<Store>,
  destination: PathBuf,
  digest: Digest,
) -> BoxFuture<(), ExitError> {
  store
    .load_file_bytes_with(digest, move |bytes| {
      File::create(&destination)
        .and_then(|mut f| f.write_all(&bytes))
        .map_err(|e| {
          format!("Error writing file {:?}: {}", destination, e.description())
        })
    })
    .map_err(|e| e.into())
    .and_then(move |write_result| match write_result {
      Some(Ok(())) => Ok(()),
      Some(Err(e)) => Err(e.into()),
      None => {
        Err(ExitError(
          format!("File with digest {:?} not found", digest),
          ExitCode::NotFound,
        ))
      }
    })
    .to_boxed()
}

fn make_clean_dir(path: &Path) -> Result<(), io::Error> {
  let parent = path.parent().ok_or_else(|| {
    io::Error::new(io::ErrorKind::NotFound, format!("{:?} had no parent", path))
  })?;
  std::fs::create_dir_all(parent)?;
  std::fs::create_dir(path)
}
