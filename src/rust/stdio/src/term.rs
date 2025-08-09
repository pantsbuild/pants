// Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).
use std::fs::File;
use std::io::{Read, Write};
use std::os::unix::io::{AsRawFd, FromRawFd, IntoRawFd, RawFd};
use std::sync::Arc;

use parking_lot::Mutex;

use crate::{Console, Destination};

///
/// An implementation of Read and Write that reads from stdin and writes to stderr.
///
/// Used to implement `console::Term` for use with the `indicatif` library.
///
#[derive(Debug)]
pub(crate) struct TermDestination {
    // Optional so that it can be restored to the destination on Drop.
    console: Mutex<Option<Console>>,
    // The destination that the Console was taken from, and will be restored to.
    destination: Arc<Destination>,
}

impl TermDestination {
    pub(crate) fn new(
        console: Console,
        destination: Arc<Destination>,
    ) -> (
        TermReadDestination,
        TermWriteDestination,
        TermWriteDestination,
    ) {
        let stderr_use_color = console.stderr_use_color;
        let term_destination = Arc::new(TermDestination {
            console: Mutex::new(Some(console)),
            destination,
        });
        (
            TermReadDestination(term_destination.clone()),
            TermWriteDestination {
                destination: term_destination.clone(),
                use_color: false,
                is_stderr: false,
            },
            TermWriteDestination {
                destination: term_destination,
                use_color: stderr_use_color,
                is_stderr: true,
            },
        )
    }
}

#[derive(Debug)]
pub struct TermReadDestination(Arc<TermDestination>);

#[derive(Debug)]
pub struct TermWriteDestination {
    destination: Arc<TermDestination>,
    pub use_color: bool,
    is_stderr: bool,
}

impl Read for TermReadDestination {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        self.0.console.lock().as_mut().unwrap().read_stdin(buf)
    }
}

impl AsRawFd for TermReadDestination {
    fn as_raw_fd(&self) -> RawFd {
        self.0.console.lock().as_ref().unwrap().stdin_as_raw_fd()
    }
}

impl Write for TermWriteDestination {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        if self.is_stderr {
            self.destination
                .console
                .lock()
                .as_mut()
                .unwrap()
                .write_stderr(buf)?;
        } else {
            self.destination
                .console
                .lock()
                .as_mut()
                .unwrap()
                .write_stdout(buf)?;
        }
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

impl AsRawFd for TermWriteDestination {
    fn as_raw_fd(&self) -> RawFd {
        if self.is_stderr {
            self.destination
                .console
                .lock()
                .as_ref()
                .unwrap()
                .stderr_as_raw_fd()
        } else {
            self.destination
                .console
                .lock()
                .as_ref()
                .unwrap()
                .stdout_as_raw_fd()
        }
    }
}

impl Drop for TermDestination {
    fn drop(&mut self) {
        self.destination
            .exclusive_clear(self.console.lock().take().unwrap())
    }
}

///
/// Attempt to clone the file handle behind this destination to turn it into an owned File
/// reference which can be closed independently.
///
/// Roughly equivalent to `File::try_clone`.
///
pub trait TryCloneAsFile {
    fn try_clone_as_file(&self) -> std::io::Result<File>;
}

impl<T: AsRawFd> TryCloneAsFile for T {
    fn try_clone_as_file(&self) -> std::io::Result<File> {
        let raw_fd = self.as_raw_fd();
        unsafe {
            let underlying_file = File::from_raw_fd(raw_fd);
            let cloned = underlying_file.try_clone()?;
            // Drop the temporarily materialized file now that we've duped it.
            let _ = underlying_file.into_raw_fd();
            Ok(cloned)
        }
    }
}
