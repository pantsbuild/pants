// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
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
#![type_length_limit = "2058438"]

#[cfg(test)]
mod tests;

use std::collections::HashMap;
use std::future::Future;
use std::io;
use std::net::Ipv4Addr;
use std::os::unix::io::{AsRawFd, FromRawFd, IntoRawFd, RawFd};
use std::path::PathBuf;
use std::sync::Arc;

use bytes::Bytes;
use futures::channel::{mpsc, oneshot};
use futures::{future, sink, stream, FutureExt, SinkExt, StreamExt, TryStreamExt};
use log::{debug, error, info};
pub use nails::execution::ExitCode;
use nails::execution::{self, send_to_io, sink_for, stream_for, ChildInput, ChildOutput};
use nails::Nail;
use tokio::fs::File;
use tokio::net::TcpListener;
use tokio::sync::watch;

use task_executor::Executor;

pub struct Server {
  exit_sender: oneshot::Sender<()>,
  state: watch::Receiver<ServerState>,
}

impl Server {
  ///
  /// Spawn the server on a background Task.
  ///
  /// The port provided here may be `0` in order to request a random port. A caller should call
  /// `await_bound` to wait for the server to have bound a port to determine what port was actually
  /// selected.
  ///
  pub async fn new(
    executor: Executor,
    port_requested: u16,
    runner: impl RawFdRunner + 'static,
  ) -> Result<Server, String> {
    let listener = TcpListener::bind((Ipv4Addr::new(127, 0, 0, 1), port_requested))
      .await
      .map_err(|e| format!("Could not bind to port {}: {:?}", port_requested, e))?;
    let port_actual = listener
      .local_addr()
      .map_err(|e| format!("No local address for listener: {:?}", e))?
      .port();

    // NB: The C client requires noisy_stdin (see the `nails` crate for more info), but neither
    // `nails` nor the pants python client do.
    let config = nails::Config::new(RawFdNail {
      executor: executor.clone(),
      runner: Arc::new(runner),
    })
    .noisy_stdin(false);

    // TODO: No longer necessary to differentiate starting from Bound.
    let (state_sender, state_receiver) = watch::channel(ServerState::Bound(port_actual));
    let (exit_sender, exit_receiver) = oneshot::channel();

    let _join = executor.spawn(Self::serve(
      executor.clone(),
      config,
      exit_receiver,
      state_sender,
      listener,
    ));

    Ok(Server {
      exit_sender,
      state: state_receiver,
    })
  }

  ///
  /// The main loop of the server. Public for testing.
  ///
  pub(crate) async fn serve<N: Nail>(
    executor: Executor,
    config: nails::Config<N>,
    should_exit: oneshot::Receiver<()>,
    state: watch::Sender<ServerState>,
    listener: TcpListener,
  ) {
    let exit_result = Self::accept_loop(executor, config, should_exit, listener).await;
    info!("Server exiting with {:?}", exit_result);
    let _ = state.broadcast(ServerState::Exited(exit_result));
  }

  async fn accept_loop<N: Nail>(
    executor: Executor,
    config: nails::Config<N>,
    _should_exit: oneshot::Receiver<()>,
    mut listener: TcpListener,
  ) -> Result<(), String> {
    loop {
      let tcp_stream = match listener.accept().await {
        Ok((tcp_stream, _addr)) => tcp_stream,
        Err(e) => {
          break Err(format!("Server failed to accept connections: {}", e));
        }
      };

      debug!("Accepted connection: {:?}", tcp_stream);
      let _join = executor.spawn(nails::server_handle_connection(config.clone(), tcp_stream));
    }
  }

  ///
  /// Returns a Future that will wait for the server to have bound its port and then return it, or
  /// return an error if the server has exited.
  ///
  pub fn await_bound(&self) -> impl Future<Output = Result<u16, String>> {
    let state_receiver = self.state.clone();
    async move {
      match *state_receiver.borrow() {
        ServerState::Bound(port) => return Ok(port),
        ServerState::Exited(ref e) => return Err(format!("Server exited with {:?}", e)),
      };
    }
  }

  ///
  /// Signal to the server that it should shut down, but do not wait for it to have shut down.
  ///
  pub fn shutdown(self) {
    // If we fail to send the exit signal, it's because the task is already shut down.
    let _ = self.exit_sender.send(());
  }
}

#[derive(Clone)]
pub enum ServerState {
  Bound(u16),
  Exited(Result<(), String>),
}

pub struct RawFdExecution {
  pub cmd: execution::Command,
  pub stdin_fd: RawFd,
  pub stdout_fd: RawFd,
  pub stderr_fd: RawFd,
}

///
/// Implementations of this trait should _not_ close the input file handles, and should let the
/// caller do so instead.
///
pub trait RawFdRunner: Fn(RawFdExecution) -> ExitCode + Send + Sync {}

impl<T: Fn(RawFdExecution) -> ExitCode + Send + Sync> RawFdRunner for T {}

///
/// A Nail implementation that proxies stdio to file handles that can be consumed by the given
/// callback function.
///
/// If any of stdio is a tty (detected via environment variables special cased in our nailgun
/// client), we ignore the input fds and open new fds directly to the tty path, which happens to
/// be addressable as a file in OSX and Linux. In that case, there is no middle-man, and we
/// ignore the fds opened by the nailgun server for data sent via the protocol.
///
#[derive(Clone)]
struct RawFdNail {
  executor: Executor,
  runner: Arc<dyn RawFdRunner>,
}

impl Nail for RawFdNail {
  fn spawn(
    &self,
    cmd: execution::Command,
    mut output_sink: mpsc::Sender<ChildOutput>,
    input_stream: mpsc::Receiver<ChildInput>,
  ) -> Result<bool, io::Error> {
    let env = cmd.env.iter().cloned().collect::<HashMap<_, _>>();

    // Handle stdin.
    let (stdin_handle, stdin_sink) = Self::input(Self::ttypath_from_env(&env, 0))?;
    let should_send_stdin = if let Some(mut stdin_sink) = stdin_sink {
      // We're using a pipe: spawn a task to copy stdin to the child.
      let mut bounded_input_stream = input_stream
        .take_while(|child_input| match child_input {
          &ChildInput::Stdin(_) => future::ready(true),
          &ChildInput::StdinEOF => future::ready(false),
        })
        .map(|child_input| match child_input {
          ChildInput::Stdin(bytes) => Ok(bytes),
          ChildInput::StdinEOF => unreachable!(),
        });
      let _join = self.executor.spawn(async move {
        stdin_sink
          .send_all(&mut bounded_input_stream)
          .map(|_| ())
          .await;
      });
      true
    } else {
      // Stdin will be handled directly by the TTY.
      false
    };

    // And stdout/stderr.
    let (stdout_stream, stdout_handle) = Self::output(Self::ttypath_from_env(&env, 1))?;
    let (stderr_stream, stderr_handle) = Self::output(Self::ttypath_from_env(&env, 2))?;

    // Spawn the underlying function as a blocking task, and capture its exit code to append to the
    // output stream.
    let nail = self.clone();
    let exit_code_future = self.executor.spawn_blocking(move || {
      // NB: This closure captures the stdio handles, and will drop/close them when it completes.
      (nail.runner)(RawFdExecution {
        cmd,
        stdin_fd: stdin_handle.as_raw_fd(),
        stdout_fd: stdout_handle.as_raw_fd(),
        stderr_fd: stderr_handle.as_raw_fd(),
      })
    });

    // Spawn a task to send all of stdout/sterr/exit to the output sink.
    let _join = self.executor.spawn(async move {
      let mut output_stream = stream::select(
        stdout_stream.map_ok(ChildOutput::Stdout),
        stderr_stream.map_ok(ChildOutput::Stderr),
      );
      while let Some(child_output) = output_stream.next().await {
        match child_output {
          Ok(child_output) => output_sink.send(child_output).await.map_err(send_to_io)?,
          Err(e) => {
            error!(
              "Failed to read nailgun output: {}. Exiting unsuccessfully.",
              e
            );
            output_sink
              .send(ChildOutput::Exit(ExitCode(-1)))
              .await
              .map_err(send_to_io)?;
            return Err(e);
          }
        }
      }
      output_sink
        .send(ChildOutput::Exit(exit_code_future.await))
        .await
        .map_err(send_to_io)?;
      Ok(())
    });

    Ok(should_send_stdin)
  }
}

impl RawFdNail {
  ///
  /// Returns a tuple of a readable file handle and an optional sink for nails to send stdin to.
  ///
  /// In the case of a TTY, the file handle will point directly to the TTY, and no stdin data will
  /// flow over the protocol. Otherwise, it will be backed by a new anonymous pipe, and data should
  /// be copied to the returned Sink.
  ///
  fn input(
    tty_path: Option<PathBuf>,
  ) -> Result<(Box<dyn AsRawFd + Send>, Option<impl sink::Sink<Bytes>>), io::Error> {
    if let Some(tty_path) = tty_path {
      Ok((Box::new(std::fs::File::open(tty_path)?), None))
    } else {
      let (stdin_reader, stdin_writer) = os_pipe::pipe()?;
      let write_handle =
        File::from_std(unsafe { std::fs::File::from_raw_fd(stdin_writer.into_raw_fd()) });
      Ok((Box::new(stdin_reader), Some(sink_for(write_handle))))
    }
  }

  ///
  /// Returns a tuple of a possibly empty Stream for nails to read data from, and a writable file handle.
  ///
  /// See `Self::input` and the struct's rustdoc for more info on the TTY case.
  ///
  #[allow(clippy::type_complexity)]
  fn output(
    tty_path: Option<PathBuf>,
  ) -> Result<
    (
      stream::BoxStream<'static, Result<Bytes, io::Error>>,
      Box<dyn AsRawFd + Send>,
    ),
    io::Error,
  > {
    if let Some(tty_path) = tty_path {
      let tty = std::fs::OpenOptions::new()
        .write(true)
        .create(false)
        .open(tty_path)?;
      Ok((stream::empty().boxed(), Box::new(tty)))
    } else {
      let (stdin_reader, stdin_writer) = os_pipe::pipe()?;
      let read_handle =
        File::from_std(unsafe { std::fs::File::from_raw_fd(stdin_reader.into_raw_fd()) });
      Ok((stream_for(read_handle).boxed(), Box::new(stdin_writer)))
    }
  }

  ///
  /// Corresponds to `ttynames_to_env` in `nailgun_protocol.py`. See this struct's rustdocs.
  ///
  fn ttypath_from_env(env: &HashMap<String, String>, fd_number: usize) -> Option<PathBuf> {
    env
      .get(&format!("NAILGUN_TTY_PATH_{}", fd_number))
      .map(PathBuf::from)
  }
}
