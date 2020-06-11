use crate::Server;

use std::path::PathBuf;

use nails::client_handle_connection;
use nails::execution::{child_channel, ChildInput, ChildOutput, Command, ExitCode};
use task_executor::Executor;
use tokio::net::TcpStream;
use tokio::runtime::Handle;

#[tokio::test]
async fn spawn_and_bind() {
  let server = Server::new(Executor::new(Handle::current()), 0, |_| ExitCode(0))
    .await
    .unwrap();
  // Should have bound a random port.
  assert!(0 != server.port());
  server.shutdown().await.unwrap();
}

#[tokio::test]
async fn accept() {
  let exit_code = ExitCode(42);
  let server = Server::new(Executor::new(Handle::current()), 0, move |_| exit_code)
    .await
    .unwrap();

  // And connect with a client. This Nail will ignore the content of the command, so we're
  // only validating the exit code.
  let cmd = Command {
    command: "nothing".to_owned(),
    args: vec![],
    env: vec![],
    working_dir: PathBuf::from("/dev/null"),
  };
  let (stdio_write, _stdio_read) = child_channel::<ChildOutput>();
  let (_stdin_write, stdin_read) = child_channel::<ChildInput>();
  let stream = TcpStream::connect(("127.0.0.1", server.port()))
    .await
    .unwrap();
  let actual_exit_code = client_handle_connection(stream, cmd, stdio_write, stdin_read)
    .await
    .unwrap();
  assert_eq!(exit_code, actual_exit_code);
  server.shutdown().await.unwrap();
}
