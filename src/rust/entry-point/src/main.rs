use nails;
use std::path::{Path, PathBuf};
use std::io::Write;
use nails::execution::{child_channel, ChildInput, ChildOutput};
use futures::{future, Stream, StreamExt, TryFutureExt};

/// This is the same as the python type `PantsDaemon.Handle`.
#[derive(Debug)]
struct PantsdHandle {
  pid: u32,
  port: u16,
  metadata_base_dir: String
}

struct PantsCommandSetup {
  python_interpreter_path: String,
  python_entry_point: String,
  pants_dir: PathBuf,
  argument_list: Vec<String>,
  env: Vec<(String, String)>,
}

impl PantsCommandSetup {
  fn to_stdlib_command(self) -> std::process::Command {
    let mut c = std::process::Command::new(self.python_interpreter_path);
    c.current_dir(self.pants_dir)
     .arg(self.python_entry_point)
     .args(self.argument_list)
     .envs(self.env);
    c
  }

  fn to_nails_command(self) -> nails::execution::Command {
    let time = get_current_time();
    println!("TIME: {}", time);
    let mut effective_env: Vec<(String, String)> = vec![
      ("PANTSD_RUNTRACKER_CLIENT_START_TIME".to_string(), time),
      ("PANTSD_REQUEST_TIMEOUT_LIMIT".to_string(), "60.0".to_string()), //TODO this should come from an option pantsd_timeout_when_multiple
    ];

    effective_env.extend(self.env);

    nails::execution::Command {
      command: "pants".to_string(),
      args: self.argument_list,
      env: effective_env,
      working_dir: self.pants_dir
    }
  }
}

/// We expect to invoke this from the `pants` script, with the first argument being the
/// path to the specific python interpreter set up by the venv.
fn main() {
    let mut args = std::env::args();
    args.next();
    let python_interpreter_path = args.next().expect("Expected a path to the pants venv python interpreter");
    //TODO should read PYTHONPATH from config and set it explicitly, instead of being an env var
    let env: Vec<(String, String)> = std::env::vars().collect();

    let pants_dir = PathBuf::from("/home/gregs/code/pants"); //TODO fix this
    let entry_point_file = "src/python/pants/bin/pants_runner.py";
    let python_entry_point = pants_dir.join(entry_point_file)
      .display().to_string();

    let argument_list: Vec<String> = args.collect();
    println!("Effective args: {:?}", argument_list);

    let using_pantsd = argument_list.iter().any(|arg| arg == "--enable-pantsd"); //TODO make this check more robust!

    let setup = PantsCommandSetup {
      python_interpreter_path,
      python_entry_point,
      pants_dir,
      argument_list,
      env
    };

    if using_pantsd {
      run_with_pantsd(setup)
    } else {
      run_locally(setup)
    }
}

fn run_locally(setup: PantsCommandSetup) {
    let child_process = setup.to_stdlib_command()
      .spawn();

    match child_process {
      Ok(mut child) => {
        println!("Running pants from rust!");
        let result = child.wait();
        if let Err(e) = result {
          println!("Another err: {}", e);
        }
      },
      Err(e) => {
        println!("Error executing pants: {}", e)
      }
    }
}

fn get_current_time() -> String {
  let now = std::time::SystemTime::now();
  let duration = now.duration_since(std::time::UNIX_EPOCH).unwrap();
  format!("{}.{}", duration.as_secs(), duration.subsec_millis())
}

//need to get value of --pants-subprocessdir (defualt .pids) to read directory
fn run_with_pantsd(setup: PantsCommandSetup) {
  use std::net::SocketAddr;

  use tokio::net::TcpStream;
  use tokio::runtime::Runtime;

  println!("Running with pantsd");
  let pantsd_dir = PathBuf::from("/home/gregs/code/pants/.pids/pantsd");
  let socket_file = pantsd_dir.join("socket_pailgun");
  if !Path::is_file(&socket_file) {
    println!("No pantsd running, falling back to local");
    run_locally(setup);
    return;
  }
  let port = std::fs::read_to_string(&socket_file).unwrap(); //TODO fix unwrap
  let port = port.parse::<u16>().unwrap();
  println!("Pantsd port: {}", port);
  let pantsd_addr = SocketAddr::new("127.0.0.1".parse().unwrap(), port);

  let mut runtime = Runtime::new().unwrap();

  let cmd = setup.to_nails_command();
  let (stdio_write, stdio_read) = child_channel::<ChildOutput>();
  let (_, stdin_read) = child_channel::<ChildInput>();

   let connection = TcpStream::connect(&pantsd_addr)
        .and_then(|stream| nails::client_handle_connection(stream, cmd, stdio_write, stdin_read))
        .map_err(|e| format!("Error communicating with server: {}", e));

  let exit_code = runtime
    .block_on(future::join(connection, print_stdio(stdio_read)))
    .0.unwrap();

  println!("Exiting with: {}", exit_code.0);
  std::process::exit(0);
}

async fn print_stdio(
    mut stdio_read: impl Stream<Item = ChildOutput> + Unpin,
) -> Result<(), std::io::Error> {
    while let Some(output) = stdio_read.next().await {
        match output {
            ChildOutput::Stdout(bytes) => std::io::stdout().write_all(&bytes)?,
            ChildOutput::Stderr(bytes) => std::io::stderr().write_all(&bytes)?,
            ChildOutput::Exit(_) => {
                // NB: We ignore exit here and allow the main thread to handle exiting.
                break;
            }
        }
    }
    Ok(())
}
