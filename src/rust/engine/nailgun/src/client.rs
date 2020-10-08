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

use nails::execution::{ChildInput, ChildOutput, ExitCode};
use nails::Config;
use tokio::net::TcpStream;

use std::io;
use std::net::Ipv4Addr;
use tokio::io::AsyncWriteExt;

use futures::channel::{mpsc, oneshot};
use futures::{future, FutureExt, SinkExt, Stream, StreamExt};
use log::debug;

pub enum NailgunClientError {
  PreConnect(String),
  PostConnect(String),
  ExplicitQuit,
}

async fn handle_client_output(
  mut stdio_read: impl Stream<Item = ChildOutput> + Unpin,
) -> Result<(), io::Error> {
  let mut stdout = tokio::io::stdout();
  let mut stderr = tokio::io::stderr();
  while let Some(output) = stdio_read.next().await {
    match output {
      ChildOutput::Stdout(bytes) => stdout.write_all(&bytes).await?,
      ChildOutput::Stderr(bytes) => stderr.write_all(&bytes).await?,
      ChildOutput::Exit(_) => {
        // NB: We ignore exit here and allow the main thread to handle exiting.
        break;
      }
    }
  }
  Ok(())
}

async fn handle_client_input(mut stdin_write: mpsc::Sender<ChildInput>) -> Result<(), io::Error> {
  use nails::execution::send_to_io;
  use std::io::Read;
  use tokio::sync::mpsc::{UnboundedSender, UnboundedReceiver};
  use bytes::Bytes;

  let (sender, mut receiver): (UnboundedSender<Box<[u8]>>, UnboundedReceiver<Box<[u8]>>) = tokio::sync::mpsc::unbounded_channel();

  let _handle = tokio::task::spawn_blocking(move || {
    let mut sync_stdin = std::io::stdin();
    let mut buf = vec![0; 8196];
    while let Ok(ret) = sync_stdin.read(&mut buf[..]) {
      let content = buf[0..ret].to_vec().into_boxed_slice();
      match sender.send(content) {
        Ok(()) => (),
        Err(_) => break,
      }
    }
  });

  while let Some(input_bytes) = receiver.recv().await {
    let bytes = Bytes::copy_from_slice(&input_bytes);
    stdin_write
      .send(ChildInput::Stdin(bytes))
      .await
      .map_err(send_to_io)?;
  }
  stdin_write
    .send(ChildInput::StdinEOF)
    .await
    .map_err(send_to_io)?;
  Ok(())
}

async fn client_execute_helper(
  port: u16,
  command: String,
  args: Vec<String>,
  env: Vec<(String, String)>,
) -> Result<i32, NailgunClientError> {
  use nails::execution::{child_channel, Command};

  let working_dir =
    std::env::current_dir().map_err(|e| NailgunClientError::PreConnect(e.to_string()))?;

  let config = Config::default();
  let command = Command {
    command,
    args,
    env,
    working_dir,
  };

  let (stdio_write, stdio_read) = child_channel::<ChildOutput>();
  let (stdin_write, stdin_read) = child_channel::<ChildInput>();

  let output_handler = tokio::spawn(handle_client_output(stdio_read));
  let _input_handler = tokio::spawn(handle_client_input(stdin_write));

  let localhost = Ipv4Addr::new(127, 0, 0, 1);
  let addr = (localhost, port);

  let socket = TcpStream::connect(addr).await.map_err(|err| {
    NailgunClientError::PreConnect(format!(
      "Nailgun client error connecting to localhost: {}",
      err
    ))
  })?;

  let exit_code: ExitCode =
    nails::client_handle_connection(config, socket, command, stdio_write, stdin_read)
      .await
      .map_err(|err| NailgunClientError::PostConnect(format!("Nailgun client error: {}", err)))?;

  let _ = _input_handler.await;

  let () = output_handler
    .await
    .map_err(|join_error| {
      NailgunClientError::PostConnect(format!("Error joining nailgun client task: {}", join_error))
    })?
    .map_err(|err| {
      NailgunClientError::PostConnect(format!("Nailgun client output error: {}", err))
    })?;

  Ok(exit_code.0)
}

pub async fn client_execute(
  port: u16,
  command: String,
  args: Vec<String>,
  env: Vec<(String, String)>,
  exit_receiver: oneshot::Receiver<()>,
) -> Result<i32, NailgunClientError> {
  use future::Either;

  let execution_future = client_execute_helper(port, command, args, env).boxed();

  match future::select(execution_future, exit_receiver).await {
    Either::Left((execution_result, _exit_receiver_fut)) => {
      debug!("Nailgun client future finished");
      execution_result
    }
    Either::Right((_exited, _execution_result_future)) => Err(NailgunClientError::ExplicitQuit),
  }
}
