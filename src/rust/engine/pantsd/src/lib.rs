// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
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

pub mod pantsd_testing;
#[cfg(test)]
mod pantsd_tests;

use std::fs;
use std::path::{Path, PathBuf};

use libc::pid_t;
use log::debug;
use options::{option_id, BuildRoot, OptionId, OptionParser, OptionType};
use sha2::digest::Update;
use sha2::{Digest, Sha256};
use sysinfo::{ProcessExt, ProcessStatus, System, SystemExt};

pub struct ConnectionSettings {
  pub port: u16,
  pub timeout_limit: f64,
  pub dynamic_ui: bool,
}

impl ConnectionSettings {
  pub fn new(port: u16) -> ConnectionSettings {
    ConnectionSettings {
      port,
      timeout_limit: 60.0,
      dynamic_ui: true,
    }
  }
}

pub(crate) struct Metadata {
  metadata_dir: PathBuf,
}

impl Metadata {
  pub(crate) fn mount<P: AsRef<Path>>(directory: P) -> Result<Metadata, String> {
    let info = uname::uname().map_err(|e| format!("{e}"))?;
    let host_hash = Sha256::new()
      .chain(&info.sysname)
      .chain(&info.nodename)
      .chain(&info.release)
      .chain(&info.version)
      .chain(&info.machine)
      .finalize();

    const HOST_FINGERPRINT_LENGTH: usize = 6;
    let hex_digest = hex::encode(&host_hash[..HOST_FINGERPRINT_LENGTH]);

    let metadata_dir = directory.as_ref().join(hex_digest).join("pantsd");
    if metadata_dir.is_dir() {
      Ok(Metadata { metadata_dir })
    } else {
      Err(format!(
        "There is no pantsd metadata at {metadata_dir}.",
        metadata_dir = metadata_dir.display()
      ))
    }
  }

  fn pid(&self) -> Result<pid_t, String> {
    self
      .read_metadata("pid")
      .and_then(|(pid_metadata_path, value)| {
        value
          .parse()
          .map(|pid| {
            debug!(
              "Parsed pid {pid} from {pid_metadata_path}.",
              pid = pid,
              pid_metadata_path = pid_metadata_path.display()
            );
            pid
          })
          .map_err(|e| {
            format!(
              "Failed to parse pantsd pid from {pid_metadata_path}: {err}",
              pid_metadata_path = pid_metadata_path.display(),
              err = e
            )
          })
      })
  }

  fn process_name(&self) -> Result<String, String> {
    self.read_metadata("process_name").map(|(_, value)| value)
  }

  pub(crate) fn port(&self) -> Result<u16, String> {
    self
      .read_metadata("socket")
      .and_then(|(socket_metadata_path, value)| {
        value
          .parse()
          .map(|port| {
            debug!(
              "Parsed port {port} from {socket_metadata_path}.",
              port = port,
              socket_metadata_path = socket_metadata_path.display()
            );
            port
          })
          .map_err(|e| {
            format!(
              "Failed to parse pantsd port from {socket_metadata_path}: {err}",
              socket_metadata_path = &socket_metadata_path.display(),
              err = e
            )
          })
      })
  }

  fn fingerprint(&self) -> Result<Fingerprint, String> {
    self.read_metadata("fingerprint").map(|(_, value)| value)
  }

  fn read_metadata(&self, name: &str) -> Result<(PathBuf, String), String> {
    let metadata_path = self.metadata_dir.join(name);
    fs::read_to_string(&metadata_path)
      .map_err(|e| {
        format!(
          "Failed to read {name} from {metadata_path}: {err}",
          name = name,
          metadata_path = &metadata_path.display(),
          err = e
        )
      })
      .map(|value| (metadata_path, value))
  }
}

pub struct FingerprintedOption {
  pub id: OptionId,
  pub option_type: OptionType,
}

impl FingerprintedOption {
  pub fn new(id: OptionId, option_type: impl Into<OptionType>) -> Self {
    Self {
      id,
      option_type: option_type.into(),
    }
  }
}

type Fingerprint = String;

/// If there is a live `pantsd` process for a valid fingerprint in the given build root, return the
/// ConnectionSettings to use to connect to it.
pub fn find_pantsd(
  build_root: &BuildRoot,
  options_parser: &OptionParser,
) -> Result<ConnectionSettings, String> {
  let pants_subprocessdir = option_id!("pants", "subprocessdir");
  let option_value = options_parser.parse_string(
    &pants_subprocessdir,
    Path::new(".pants.d").join("pids").to_str().unwrap(),
  )?;
  let metadata_dir = {
    let path = PathBuf::from(&option_value.value);
    if path.is_absolute() {
      path
    } else {
      match build_root.join(&path) {
        p if p.is_absolute() => p,
        p => p.canonicalize().map_err(|e| {
          format!(
            "Failed to resolve relative pants subprocessdir specified via {:?} as {}: {}",
            option_value,
            path.display(),
            e
          )
        })?,
      }
    }
  };
  debug!(
    "\
    Looking for pantsd metadata in {metadata_dir} as specified by {option} = {value} via \
    {source:?}.\
    ",
    metadata_dir = metadata_dir.display(),
    option = pants_subprocessdir,
    value = option_value.value,
    source = option_value.source
  );
  let port = probe(build_root, &metadata_dir, options_parser)?;
  let mut pantsd_settings = ConnectionSettings::new(port);
  pantsd_settings.timeout_limit = options_parser
    .parse_float(
      &option_id!("pantsd", "timeout", "when", "multiple", "invocations"),
      pantsd_settings.timeout_limit,
    )?
    .value;
  pantsd_settings.dynamic_ui = options_parser
    .parse_bool(&option_id!("dynamic", "ui"), pantsd_settings.dynamic_ui)?
    .value;
  Ok(pantsd_settings)
}

pub(crate) fn probe(
  build_root: &BuildRoot,
  metadata_dir: &Path,
  options_parser: &OptionParser,
) -> Result<u16, String> {
  let pantsd_metadata = Metadata::mount(metadata_dir)?;

  // Grab the purported port early. If we can't get that, then none of the following checks
  // are useful.
  let port = pantsd_metadata.port()?;

  let expected_fingerprint = pantsd_metadata.fingerprint()?;
  let actual_fingerprint = fingerprint_compute(build_root, options_parser)?;
  if expected_fingerprint != actual_fingerprint {
    return Err(format!(
      "Fingerprint mismatched: {expected_fingerprint} vs {actual_fingerprint}."
    ));
  }

  let pid = pantsd_metadata.pid()?;
  let mut system = System::new();
  system.refresh_process(pid);
  // Check that the recorded pid is a live process.
  match system.process(pid) {
    None => Err(format!(
      "\
        The last pid for the pantsd controlling {build_root} was {pid} but it no longer appears \
        to be running.\
        ",
      build_root = build_root.display(),
      pid = pid,
    )),
    Some(process) => {
      // Check that the live process is in fact the expected pantsd process (i.e.: pids have not
      // wrapped).
      if std::mem::discriminant(&ProcessStatus::Zombie) == std::mem::discriminant(&process.status())
      {
        return Err(format!("The pantsd at pid {pid} is a zombie."));
      }
      let expected_process_name_prefix = pantsd_metadata.process_name()?;
      let actual_argv0 = {
        let actual_command_line = process.cmd();
        if actual_command_line.is_empty() {
          process.name()
        } else {
          &actual_command_line[0]
        }
      };
      // It appears that the daemon only records a prefix of the process name, so we just check that.
      if actual_argv0.starts_with(&expected_process_name_prefix) {
        Ok(port)
      } else {
        Err(format!(
          "\
          The process with pid {pid} is not pantsd. Expected a process name matching \
          {expected_process_name_prefix} but is {actual_argv0}.\
          "
        ))
      }
    }
  }
}

/// Computes a fingerprint of the relevant options for `pantsd` (see `fingerprinted_options`).
///
/// This fingerprint only needs to be stable within a single version of `pantsd`, since any
/// mismatch of the fingerprint (particularly one caused by a new version) _should_ cause a
/// mismatch.
///
/// TODO: Eventually, the Python `class ProcessManager` should be replaced with the `Metadata`
/// struct in this crate, rather than having two codepaths for the reading/writing of metadata.
pub fn fingerprint_compute(
  build_root: &BuildRoot,
  options_parser: &OptionParser,
) -> Result<Fingerprint, String> {
  let mut hasher = Sha256::new();
  for option in fingerprinted_options(build_root)? {
    // TODO: As the Rust options crate expands, more of this logic should be included on
    // `OptionParser` or on `OptionValue`.
    match option.option_type {
      OptionType::Bool(default) => {
        let val = options_parser.parse_bool(&option.id, default)?;
        let byte = if val.value { 1_u8 } else { 0_u8 };
        Digest::update(&mut hasher, [byte]);
      }
      OptionType::Int(default) => {
        let val = options_parser.parse_int(&option.id, default)?;
        Digest::update(&mut hasher, val.value.to_be_bytes());
      }
      OptionType::Float(default) => {
        let val = options_parser.parse_float(&option.id, default)?;
        Digest::update(&mut hasher, val.value.to_be_bytes());
      }
      OptionType::String(default) => {
        let val = options_parser.parse_string(&option.id, &default)?;
        Digest::update(&mut hasher, val.value.as_bytes());
      }
      OptionType::StringList(default) => {
        let default = default.iter().map(|s| s.as_str()).collect::<Vec<_>>();
        let val = options_parser.parse_string_list(&option.id, &default)?;
        for item in val {
          Digest::update(&mut hasher, item.as_bytes());
        }
      }
    }
  }
  let hash = hasher.finalize();
  Ok(hex::encode(hash))
}

/// The options which are fingerprinted to decide when to restart `pantsd`.
///
/// These options are a subset of the bootstrap options which are consumed during `pantsd` startup,
/// but _before_ creating a Scheduler. The options used to create a Scheduler are fingerprinted
/// using a different mechanism in `PantsDaemonCore`, to decide when to create new Schedulers
/// (without restarting `pantsd`).
///
/// TODO: This list is exposed to Python in order to validate that it matches actual existing
/// options (because we have redundancy of options definitions between `global_options.py` and what
/// the Rust native client uses).
pub fn fingerprinted_options(build_root: &BuildRoot) -> Result<Vec<FingerprintedOption>, String> {
  let dot_pants_dot_d_subdir = |subdir: &str| -> Result<String, String> {
    build_root
      .join(".pants.d")
      .join(subdir)
      .into_os_string()
      .into_string()
      .map_err(|e| format!("Build root was not UTF8: {e:?}"))
  };

  Ok(vec![
    FingerprintedOption::new(option_id!(-'l', "level"), "info"),
    FingerprintedOption::new(option_id!("show", "log", "target"), false),
    // TODO: No support for parsing dictionaries, so not fingerprinted. But should be. See #19832.
    // FingerprintedOption::new(option_id!("log", "levels", "by", "target"), ...),
    FingerprintedOption::new(option_id!("log", "show", "rust", "3rdparty"), false),
    FingerprintedOption::new(option_id!("ignore", "warnings"), vec![]),
    FingerprintedOption::new(
      option_id!("pants", "version"),
      include_str!("../../VERSION"),
    ),
    FingerprintedOption::new(
      option_id!("pants", "workdir"),
      dot_pants_dot_d_subdir("workdir")?,
    ),
    // Optional strings are not currently supported by the Rust options parser, but we're only
    // using these for fingerprinting, and so can use a placeholder default.
    FingerprintedOption::new(option_id!("pants", "physical", "workdir", "base"), "<none>"),
    FingerprintedOption::new(
      option_id!("pants", "subprocessdir"),
      dot_pants_dot_d_subdir("pids")?,
    ),
    FingerprintedOption::new(option_id!("logdir"), "<none>"),
    FingerprintedOption::new(option_id!("pantsd"), true),
    FingerprintedOption::new(option_id!("pantsd", "pailgun", "port"), 0),
    FingerprintedOption::new(option_id!("pantsd", "invalidation", "globs"), vec![]),
  ])
}
