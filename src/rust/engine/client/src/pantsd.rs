// Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::path::{Path, PathBuf};
use std::{fmt, fs};

use libc::pid_t;
use log::debug;
use sha2::digest::Update;
use sha2::{Digest, Sha256};
use sysinfo::{ProcessExt, ProcessStatus, System, SystemExt};

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

        const HOST_FINGERPRINT_LENGTH: usize = 12;
        let mut hex_digest = String::with_capacity(HOST_FINGERPRINT_LENGTH);
        for byte in host_hash {
            fmt::Write::write_fmt(&mut hex_digest, format_args!("{byte:02x}")).unwrap();
            if hex_digest.len() >= HOST_FINGERPRINT_LENGTH {
                break;
            }
        }

        let metadata_dir = directory
            .as_ref()
            .join(&hex_digest[..HOST_FINGERPRINT_LENGTH])
            .join("pantsd");
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
        self.read_metadata("pid")
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
        self.read_metadata("socket")
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

pub fn probe(working_dir: &Path, metadata_dir: &Path) -> Result<u16, String> {
    let pantsd_metadata = Metadata::mount(metadata_dir)?;

    // Grab the purported port early. If we can't get that, then none of the following checks
    // are useful.
    let port = pantsd_metadata.port()?;

    let pid = pantsd_metadata.pid()?;
    let mut system = System::new();
    system.refresh_process(pid);
    // Check that the recorded pid is a live process.
    match system.process(pid) {
        None => Err(format!(
            "\
        The last pid for the pantsd controlling {working_dir} was {pid} but it no longer appears \
        to be running.\
        ",
            working_dir = working_dir.display(),
            pid = pid,
        )),
        Some(process) => {
            // Check that the live process is in fact the expected pantsd process (i.e.: pids have not
            // wrapped).
            if std::mem::discriminant(&ProcessStatus::Zombie)
                == std::mem::discriminant(&process.status())
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
            // It appears the the daemon only records a prefix of the process name, so we just check that.
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
