use std::io::Write;

use futures::future::Future;
use futures_locks::Mutex;

use crate::stdio::{PausableStdioWriter, StdioAccess};

#[test]
fn pausable_stdio_writer_pause() {
  let test_stdio_access = Mutex::new(StdioAccess::new_for_tests());
  let mut psw = PausableStdioWriter::new_for_tests(Vec::new(), &test_stdio_access);
  // Write some data while not paused.
  psw.write_all("hello".as_bytes()).unwrap();
  psw.flush().unwrap();

  // Then more while paused.
  {
    let _guard = test_stdio_access.lock().wait();
    psw.write_all(" world!".as_bytes()).unwrap();
    psw.flush().unwrap();
  }

  // Unwrap the writer without flushing, which should discard the buffered data.
  assert_eq!(
    "hello".as_bytes().iter().cloned().collect::<Vec<_>>(),
    psw.to_inner()
  );
}

#[test]
fn pausable_stdio_writer_pause_and_resume() {
  let test_stdio_access = Mutex::new(StdioAccess::new_for_tests());
  let mut psw = PausableStdioWriter::new_for_tests(Vec::new(), &test_stdio_access);
  // Write some data while not paused.
  psw.write_all("hello".as_bytes()).unwrap();
  psw.flush().unwrap();

  // Then more while paused.
  {
    let _guard = test_stdio_access.lock().wait();
    psw.write_all(" world!".as_bytes()).unwrap();
  }

  // Flush while not paused, and confirm that the entire result is available.
  psw.flush().unwrap();
  assert_eq!(
    "hello world!"
      .as_bytes()
      .iter()
      .cloned()
      .collect::<Vec<_>>(),
    psw.to_inner()
  );
}
