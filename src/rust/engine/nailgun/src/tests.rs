use crate::Server;

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use futures::{future, FutureExt};
use nails::execution::{child_channel, ChildInput, Command, ExitCode};
use nails::Config;
use task_executor::Executor;
use tokio::net::TcpStream;
use tokio::sync::Notify;
use tokio::time::sleep;

#[tokio::test]
async fn spawn_and_bind() {
    let server = Server::new(Executor::new(), 0, |_| ExitCode(0))
        .await
        .unwrap();
    // Should have bound a random port.
    assert!(0 != server.port());
    server.shutdown().await.unwrap();
}

#[tokio::test]
async fn accept() {
    let exit_code = ExitCode(42);
    let server = Server::new(Executor::new(), 0, move |_| exit_code)
        .await
        .unwrap();

    // And connect with a client. This Nail will ignore the content of the command, so we're
    // only validating the exit code.
    let actual_exit_code = run_client(server.port()).await.unwrap();
    assert_eq!(exit_code, actual_exit_code);
    server.shutdown().await.unwrap();
}

#[tokio::test]
async fn shutdown_awaits_ongoing() {
    // A server that waits for a signal to complete a connection.
    let connection_accepted = Arc::new(Notify::new());
    let should_complete_connection = Arc::new(Notify::new());
    let exit_code = ExitCode(42);
    let server = Server::new(Executor::new(), 0, {
        let connection_accepted = connection_accepted.clone();
        let should_complete_connection = should_complete_connection.clone();
        move |_| {
            connection_accepted.notify_one();
            tokio::runtime::Handle::current().block_on(should_complete_connection.notified());
            exit_code
        }
    })
    .await
    .unwrap();

    // Spawn a connection in the background, and once it has been established, kick off shutdown of
    // the server.
    let mut client_completed = tokio::spawn(run_client(server.port()));
    connection_accepted.notified().await;
    let mut server_shutdown = tokio::spawn(server.shutdown());

    // Confirm that the client doesn't return, and that the server doesn't shutdown.
    match future::select(client_completed, sleep(Duration::from_millis(500)).boxed()).await {
        future::Either::Right((_, c_c)) => client_completed = c_c,
        _ => panic!("Client should not have completed"),
    }
    match future::select(server_shutdown, sleep(Duration::from_millis(500)).boxed()).await {
        future::Either::Right((_, s_s)) => server_shutdown = s_s,
        _ => panic!("Server should not have shut down"),
    }

    // Then signal completion of the connection, and confirm that both the client and server exit
    // cleanly.
    should_complete_connection.notify_one();
    assert_eq!(exit_code, client_completed.await.unwrap().unwrap());
    server_shutdown.await.unwrap().unwrap();
}

async fn run_client(port: u16) -> Result<ExitCode, String> {
    let cmd = Command {
        command: "nothing".to_owned(),
        args: vec![],
        env: vec![],
        working_dir: PathBuf::from("/dev/null"),
    };
    let stream = TcpStream::connect(("127.0.0.1", port)).await.unwrap();
    let child = nails::client::handle_connection(Config::default(), stream, cmd, async {
        let (_stdin_write, stdin_read) = child_channel::<ChildInput>();
        stdin_read
    })
    .await
    .map_err(|e| e.to_string())?;
    child.wait().await.map_err(|e| e.to_string())
}
