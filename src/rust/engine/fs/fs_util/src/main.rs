extern crate bazel_protos;
extern crate clap;
extern crate fs;

use clap::{App, Arg, SubCommand};
use fs::hash::Fingerprint;
use fs::store::Store;
use std::error::Error;
use std::fs::{DirEntry, File, read_dir};
use std::io::{self, Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::exit;

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
              )),
          )
          .subcommand(
            SubCommand::with_name("save")
              .about(
                "Ingest a file by path, which allows it to be used in Directories/Snapshots. \
Outputs a fingerprint of its contents.",
              )
              .arg(Arg::with_name("path").required(true).takes_value(true)),
          ),
      )
      .subcommand(
        SubCommand::with_name("directory").subcommand(
          SubCommand::with_name("save")
            .about(
              "Ingest a directory recursively. Saves all files found therein and saves Directory \
protos for each directory found. Outputs a fingerprint of the canonical top-level Directory proto.",
            )
            .arg(Arg::with_name("source").required(true).takes_value(true)),
        ),
      )
      .arg(
        Arg::with_name("store_dir")
            .takes_value(true)
            // TODO: Default this to wherever pants actually stores this.
            .default_value("/tmp/lmdb"),
      )
      .get_matches(),
  ) {
    Ok(_) => {}
    Err(err) => {
      eprintln!("{}", err);
      exit(1)
    }
  };
}

fn execute(top_match: clap::ArgMatches) -> Result<(), String> {
  let store_dir = top_match.value_of("store_dir").unwrap();
  let store = Store::new(store_dir).map_err(|e| {
    format!(
      "Failed to open/create store for directory {}: {}",
      store_dir,
      e
    )
  })?;

  match top_match.subcommand() {
    ("file", Some(sub_match)) => {
      match sub_match.subcommand() {
        ("cat", Some(args)) => {
          let fingerprint = Fingerprint::from_hex_string(args.value_of("fingerprint").unwrap())?;
          match store.load_bytes(&fingerprint).unwrap() {
            Some(bytes) => {
              io::stdout().write(&bytes).unwrap();
              Ok(())
            }
            None => Err(format!("File with fingerprint {} not found", fingerprint)),
          }
        }
        ("save", Some(args)) => {
          save_file(&store, &PathBuf::from(args.value_of("path").unwrap()))
            .map(|(fingerprint, _)| println!("{}", fingerprint))
        }
        (_, _) => unimplemented!(),
      }
    }
    ("directory", Some(sub_match)) => {
      match sub_match.subcommand() {
        ("save", Some(args)) => {
          save_directory(&store, &PathBuf::from(args.value_of("source").unwrap()))
            .map(|(fingerprint, _)| println!("{}", fingerprint))
        }
        (_, _) => unimplemented!(),
      }
    }
    (_, _) => unimplemented!(),
  }
}

fn save_file(store: &Store, path: &Path) -> Result<(Fingerprint, usize), String> {
  let mut buf = Vec::new();
  File::open(path)
    .and_then(|mut f| f.read_to_end(&mut buf))
    .map_err(|e| {
      format!("Error reading file {:?}: {}", path, e.description())
    })?;
  Ok((store.store_file_bytes(&buf)?, buf.len()))
}

fn save_directory(store: &Store, root: &Path) -> Result<(Fingerprint, usize), String> {
  let mut directory = bazel_protos::remote_execution::Directory::new();
  for maybe_entry in read_dir(root).map_err(|e| {
    format!("Error reading dir {:?}: {}", root, e.description())
  })?
  {
    let entry = maybe_entry.map_err(|e| {
      format!(
        "Error reading dir entry within {:?}: {}",
        root,
        e.description()
      )
    })?;
    let metadata = entry.metadata().map_err(|e| {
      format!(
        "Error stating file {:?}: {}",
        entry.path(),
        e.description().to_string()
      )
    })?;
    if metadata.is_dir() {
      let (fingerprint, proto_size_bytes) = save_directory(store, &entry.path())?;
      directory.mut_directories().push({
        let mut dir_node = bazel_protos::remote_execution::DirectoryNode::new();
        dir_node.set_name(path_to_utf8(&entry, DirEntry::file_name)?);
        dir_node.set_digest(fingerprint_to_digest(&fingerprint, proto_size_bytes as i64));
        dir_node
      })
    } else if metadata.is_file() {
      let (fingerprint, size_bytes) = save_file(store, &entry.path())?;
      directory.mut_files().push({
        let mut file_node = bazel_protos::remote_execution::FileNode::new();
        file_node.set_name(path_to_utf8(&entry, DirEntry::file_name)?);
        file_node.set_digest(fingerprint_to_digest(&fingerprint, size_bytes as i64));
        file_node.set_is_executable(metadata.permissions().mode() & 1 == 1);
        file_node
      });
    }
  }
  directory.mut_directories().sort_by_key(
    |f| f.get_name().to_string(),
  );
  directory.mut_files().sort_by_key(
    |f| f.get_name().to_string(),
  );
  store.record_directory(&directory)
}

pub fn fingerprint_to_digest(
  fingerprint: &Fingerprint,
  size_bytes: i64,
) -> bazel_protos::remote_execution::Digest {
  let mut digest = bazel_protos::remote_execution::Digest::new();
  digest.set_hash(fingerprint.to_hex());
  digest.set_size_bytes(size_bytes);
  digest
}

fn path_to_utf8<F, P>(dir: &DirEntry, f: F) -> Result<String, String>
where
  F: Fn(&DirEntry) -> P,
  P: AsRef<Path>,
{
  match f(dir).as_ref().to_str() {
    Some(dir) => Ok(dir.to_string()),
    None => Err(format!(
      "Error convering file path to UTF8: {:?}",
      dir.path()
    )),
  }
}
