// Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io;
use std::net::Ipv4Addr;
use std::os::fd::OwnedFd;
use std::os::unix::io::{AsRawFd, RawFd};
use std::path::PathBuf;
use std::sync::Arc;

use async_latch::AsyncLatch;
use bytes::Bytes;
use futures::channel::oneshot;
use futures::{future, sink, stream, FutureExt, SinkExt, StreamExt, TryStreamExt};
use log::{debug, info};
use nails::execution::{self, child_channel, sink_for, ChildInput, ChildOutput, ExitCode};
use nails::Nail;
use task_executor::Executor;
use tokio::fs::File;
use tokio::net::TcpListener;
use tokio::sync::{mpsc, Notify, RwLock};
use tokio_stream::wrappers::UnboundedReceiverStream;

pub struct Server {
  exit_sender: oneshot::Sender<()>,
  exited_receiver: oneshot::Receiver<Result<(), String>>,
  port: u16,
}

impl Server {
  ///
  /// Spawn the server on a background Task.
  ///
  /// The port provided here may be `0` in order to request a random port. A caller can use
  /// `Server.port()` to determine what port was actually selected.
  ///
  pub async fn new(
    executor: Executor,
    port_requested: u16,
    runner: impl RawFdRunner + 'static,
  ) -> Result<Server, String> {
    let listener = TcpListener::bind((Ipv4Addr::new(127, 0, 0, 1), port_requested))
      .await
      .map_err(|e| format!("Could not bind to port {port_requested}: {e:?}"))?;
    let port_actual = listener
      .local_addr()
      .map_err(|e| format!("No local address for listener: {e:?}"))?
      .port();

    // NB: The C client requires noisy_stdin (see the `nails` crate for more info), but neither
    // `nails` nor the pants python client do.
    let config = nails::Config::default().noisy_stdin(false);
    let nail = RawFdNail {
      executor: executor.clone(),
      runner: Arc::new(runner),
    };

    let (exited_sender, exited_receiver) = oneshot::channel();
    let (exit_sender, exit_receiver) = oneshot::channel();

    let _join = executor.native_spawn(Self::serve(
      executor.clone(),
      config,
      nail,
      exit_receiver,
      exited_sender,
      listener,
    ));

    Ok(Server {
      exit_sender,
      exited_receiver,
      port: port_actual,
    })
  }

  ///
  /// The main loop of the server. Public for testing.
  ///
  pub(crate) async fn serve(
    executor: Executor,
    config: nails::Config,
    nail: impl Nail,
    should_exit: oneshot::Receiver<()>,
    exited: oneshot::Sender<Result<(), String>>,
    listener: TcpListener,
  ) {
    let exit_result = Self::accept_loop(executor, config, nail, should_exit, listener).await;
    info!("Server exiting with {:?}", exit_result);
    let _ = exited.send(exit_result);
  }

  async fn accept_loop(
    executor: Executor,
    config: nails::Config,
    nail: impl Nail,
    mut should_exit: oneshot::Receiver<()>,
    listener: TcpListener,
  ) -> Result<(), String> {
    // While connections are ongoing, they acquire `read`; before shutting down, the server
    // acquires `write`.
    let ongoing_connections = Arc::new(RwLock::new(()));

    let result = loop {
      let tcp_stream = match future::select(listener.accept().boxed(), should_exit).await {
        future::Either::Left((Ok((tcp_stream, _addr)), s_e)) => {
          // Got a connection.
          should_exit = s_e;
          tcp_stream
        }
        future::Either::Left((Err(e), _)) => {
          break Err(format!("Server failed to accept connections: {e}"));
        }
        future::Either::Right((_, _)) => {
          break Ok(());
        }
      };

      debug!("Accepted connection: {:?}", tcp_stream);

      // There is a slightly delicate dance here: we wait for a connection to have acquired the
      // ongoing connections lock before proceeding to the next iteration of the loop. This
      // prevents us from observing an empty lock and exiting before the connection has actually
      // acquired it. Unfortunately we cannot acquire the lock in this thread and then send the
      // guard to the other thread due to its lifetime bounds.
      let connection_started = Arc::new(Notify::new());
      let _join = executor.native_spawn({
        let config = config.clone();
        let nail = nail.clone();
        let connection_started = connection_started.clone();
        let ongoing_connections = ongoing_connections.clone();
        async move {
          let ongoing_connection_guard = ongoing_connections.read().await;
          connection_started.notify_one();
          let result = nails::server::handle_connection(config, nail, tcp_stream).await;
          std::mem::drop(ongoing_connection_guard);
          result
        }
      });
      connection_started.notified().await;
    };

    // Before exiting, acquire write access on the ongoing_connections lock to prove that all
    // connections have completed.
    debug!("Server waiting for connections to complete...");
    let _ = ongoing_connections.write().await;
    debug!("All connections completed.");
    result
  }

  ///
  /// The port that the server is listening on.
  ///
  pub fn port(&self) -> u16 {
    self.port
  }

  ///
  /// Returns a Future that will shut down the server by:
  /// 1. stopping accepting new connections
  /// 2. waiting for all ongoing connections to have completed
  ///
  pub async fn shutdown(self) -> Result<(), String> {
    // If we fail to send the exit signal, it's because the task is already shut down.
    let _ = self.exit_sender.send(());
    self
      .exited_receiver
      .await
      .map_err(|_| "Server exited uncleanly.".to_owned())?
  }
}

pub struct RawFdExecution {
  pub cmd: execution::Command,
  pub cancelled: AsyncLatch,
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
  fn spawn(&self, cmd: execution::Command) -> Result<nails::server::Child, io::Error> {
    let env = cmd.env.iter().cloned().collect::<HashMap<_, _>>();

    // Handle stdin.
    let (stdin_handle, stdin_sink) = Self::input(Self::ttypath_from_env(&env, 0))?;
    let maybe_stdin_write = if let Some(mut stdin_sink) = stdin_sink {
      let (stdin_write, stdin_read) = child_channel::<ChildInput>();
      // Spawn a task that will propagate the input stream.
      let _join = self.executor.native_spawn(async move {
        let mut input_stream = stdin_read.map(|child_input| match child_input {
          ChildInput::Stdin(bytes) => Ok(bytes),
        });
        let _ = stdin_sink.send_all(&mut input_stream).await;
      });
      Some(stdin_write)
    } else {
      // Stdin will be handled directly by the TTY.
      None
    };

    // And stdout/stderr.
    let (stdout_stream, stdout_handle) = Self::output(Self::ttypath_from_env(&env, 1), false)?;
    // N.B.: POSIX demands stderr is opened read-write and some programs, like pagers, rely on this.
    // See: https://pubs.opengroup.org/onlinepubs/9699919799/functions/stdin.html
    let (stderr_stream, stderr_handle) = Self::output(Self::ttypath_from_env(&env, 2), true)?;

    // Set up a cancellation token that is triggered on client shutdown.
    let cancelled = AsyncLatch::new();
    let shutdown = {
      let cancelled = cancelled.clone();
      async move {
        cancelled.trigger();
      }
    };

    // Spawn the underlying function as a blocking task, and capture its exit code to append to the
    // output stream.
    let nail = self.clone();
    let exit_code = self
      .executor
      .spawn_blocking(
        move || {
          // NB: This closure captures the stdio handles, and will drop/close them when it completes.
          (nail.runner)(RawFdExecution {
            cmd,
            cancelled,
            stdin_fd: stdin_handle.as_raw_fd(),
            stdout_fd: stdout_handle.as_raw_fd(),
            stderr_fd: stderr_handle.as_raw_fd(),
          })
        },
        |e| {
          log::warn!("Server exited uncleanly: {e}");
          ExitCode(1)
        },
      )
      .boxed();

    // Select a single stdout/stderr stream.
    let stdout_stream = stdout_stream.map_ok(ChildOutput::Stdout);
    let stderr_stream = stderr_stream.map_ok(ChildOutput::Stderr);
    let output_stream = stream::select(stdout_stream, stderr_stream).boxed();

    Ok(nails::server::Child::new(
      output_stream,
      maybe_stdin_write,
      exit_code,
      Some(shutdown.boxed()),
    ))
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
    if let Some(tty) = Self::try_open_tty(tty_path, OpenOptions::new().read(true)) {
      Ok((Box::new(tty), None))
    } else {
      let (pipe_reader, pipe_writer) = os_pipe::pipe()?;
      let write_handle = File::from_std(std::fs::File::from(OwnedFd::from(pipe_writer)));
      Ok((Box::new(pipe_reader), Some(sink_for(write_handle))))
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
    read_write: bool,
  ) -> Result<
    (
      stream::BoxStream<'static, Result<Bytes, io::Error>>,
      Box<dyn AsRawFd + Send>,
    ),
    io::Error,
  > {
    if let Some(tty) = Self::try_open_tty(
      tty_path,
      OpenOptions::new()
        .read(read_write)
        .write(true)
        .create(false),
    ) {
      Ok((stream::empty().boxed(), Box::new(tty)))
    } else {
      let (pipe_reader, pipe_writer) = os_pipe::pipe()?;
      let read_handle = std::fs::File::from(OwnedFd::from(pipe_reader));
      Ok((
        blocking_stream_for(read_handle)?.boxed(),
        Box::new(pipe_writer),
      ))
    }
  }

  ///
  /// Attempt to open the given TTY-path, logging any errors.
  ///
  fn try_open_tty(tty_path: Option<PathBuf>, open_options: &OpenOptions) -> Option<std::fs::File> {
    let tty_path = tty_path?;
    open_options
      .open(&tty_path)
      .map_err(|e| {
        log::debug!(
          "Failed to open TTY at {}: {:?}, falling back to socket access.",
          tty_path.display(),
          e
        );
      })
      .ok()
  }

  ///
  /// Corresponds to `ttynames_to_env` in `nailgun_protocol.py`. See this struct's rustdocs.
  ///
  fn ttypath_from_env(env: &HashMap<String, String>, fd_number: usize) -> Option<PathBuf> {
    env
      .get(&format!("NAILGUN_TTY_PATH_{fd_number}"))
      .map(PathBuf::from)
  }
}

// TODO: See https://github.com/pantsbuild/pants/issues/16969.
pub fn blocking_stream_for<R: io::Read + Send + Sized + 'static>(
  mut r: R,
) -> io::Result<impl futures::Stream<Item = Result<Bytes, io::Error>>> {
  let (sender, receiver) = mpsc::unbounded_channel();
  std::thread::Builder::new()
    .name("stdio-reader".to_owned())
    .spawn(move || {
      let mut buf = [0; 4096];
      loop {
        match r.read(&mut buf) {
          Ok(0) => break,
          Ok(n) => {
            if sender.send(Ok(Bytes::copy_from_slice(&buf[..n]))).is_err() {
              break;
            }
          }
          Err(ref e) if e.kind() == io::ErrorKind::Interrupted => {}
          Err(e) => {
            let _ = sender.send(Err(e));
            break;
          }
        }
      }
    })?;
  Ok(UnboundedReceiverStream::new(receiver))
}
