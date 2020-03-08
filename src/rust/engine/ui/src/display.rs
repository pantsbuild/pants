// Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
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

use termion;

use std::collections::{BTreeMap, VecDeque};
use std::io::Read;
use std::io::Write;
use std::io::{stdout, Result, Stdout};

use termion::raw::IntoRawMode;
use termion::raw::RawTerminal;
use termion::screen::AlternateScreen;
use termion::{async_stdin, AsyncReader};
use termion::{clear, color, cursor};
use unicode_segmentation::UnicodeSegmentation;

enum Console {
  Uninitialized,
  Terminal(RawTerminal<AlternateScreen<Stdout>>),
  Pipe(Stdout),
}

#[derive(Clone)]
struct PrintableMsg {
  msg: String,
  output: PrintableMsgOutput,
}

#[derive(Clone)]
enum PrintableMsgOutput {
  Stdout,
  Stderr,
}

pub enum KeyboardCommand {
  None,
  CtrlC,
}

pub struct EngineDisplay {
  sigil: char,
  divider: String,
  padding: String,
  terminal: Console,
  action_map: BTreeMap<String, String>,
  logs: VecDeque<String>,
  printable_msgs: VecDeque<PrintableMsg>,
  cursor_start: (u16, u16),
  terminal_size: (u16, u16),
  async_stdin: Option<AsyncReader>,
  suspended: bool,
}

// TODO: Prescribe a threading/polling strategy for callers - or implement a built-in one.
// TODO: Better error handling for .flush() and .write() failure modes.
// TODO: Permit scrollback in the terminal - both at exit and during the live run.
impl EngineDisplay {
  /// Create a new EngineDisplay
  pub fn new(indent_level: u16) -> EngineDisplay {
    EngineDisplay {
      sigil: '⚡',
      divider: "▵".to_string(),
      padding: " ".repeat(indent_level.into()),
      terminal: Console::Uninitialized,
      action_map: BTreeMap::new(),
      // This is arbitrary based on a guesstimated peak terminal row size for modern displays.
      // The reason this can't be capped to e.g. the starting size is because of resizing - we
      // want to be able to fill the entire screen if resized much larger than when we started.
      logs: VecDeque::with_capacity(500),
      printable_msgs: VecDeque::with_capacity(500),
      // N.B. This will cause the screen to clear - but with some improved position
      // tracking logic we could avoid screen clearing in favor of using the value
      // of `EngineDisplay::get_cursor_pos()` as initialization here. From there, the
      // trick would be to push the on-screen text screen up (ideally, prior to entering
      // raw mode) via newline printing - and then ensuring the rendered text never
      // overflows past the screen row bounds. Before we could safely do that tho, we
      // probably want to plumb a signal handler for SIGWINCH so that ^L works to redraw
      // the screen in the case of any display issues. Otherwise, simply clearing the screen
      // as we've done here is the safest way to avoid terminal oddness.
      cursor_start: (1, 1),
      terminal_size: EngineDisplay::get_size(),
      async_stdin: Some(async_stdin()),
      suspended: false,
    }
  }

  pub fn initialize(&mut self, display_worker_count: usize) {
    let worker_ids: Vec<String> = (0..display_worker_count)
      .map(|s| format!("{}", s))
      .collect();
    for worker_id in worker_ids {
      self.add_worker(worker_id);
    }
  }

  pub fn stdout_is_tty() -> bool {
    termion::is_tty(&stdout())
  }

  pub fn write_stdout(&mut self, msg: &str) {
    self.printable_msgs.push_back(PrintableMsg {
      msg: msg.to_string(),
      output: PrintableMsgOutput::Stdout,
    });
  }

  pub fn write_stderr(&mut self, msg: &str) {
    self.printable_msgs.push_back(PrintableMsg {
      msg: msg.to_string(),
      output: PrintableMsgOutput::Stderr,
    });
  }

  fn start_raw_mode(&mut self) -> Result<()> {
    match self.terminal {
      Console::Terminal(ref mut t) => t.activate_raw_mode(),
      _ => Ok(()),
    }
  }

  // Gets the current terminal's width and height, if applicable.
  fn get_size() -> (u16, u16) {
    termion::terminal_size().unwrap_or((0, 0))
  }

  // Sets the terminal size per-render for signal-free resize detection.
  fn set_size(&mut self) {
    self.terminal_size = EngineDisplay::get_size();
  }

  // Sets the terminal size for signal-free resize detection.
  fn get_max_log_rows(&self) -> usize {
    // TODO: If the terminal size is smaller than the action map, we should fall back
    // to non-tty mode output to avoid.
    self.terminal_size.1 as usize - self.action_map.len() - 1
  }

  // Prep the screen for painting by clearing it from the cursor start position.
  fn clear(&mut self) {
    let cursor_start = self.cursor_start;
    self
      .write(&format!(
        "{goto_origin}{clear}",
        goto_origin = cursor::Goto(cursor_start.0, cursor_start.1),
        clear = clear::AfterCursor,
      ))
      .expect("could not write to terminal");
  }

  // Flush terminal output.
  fn flush(&mut self) -> Result<()> {
    match self.terminal {
      Console::Terminal(ref mut t) => t.flush(),
      Console::Pipe(ref mut p) => p.flush(),
      Console::Uninitialized => Ok(()),
    }
  }

  // Writes output to the terminal.
  fn write(&mut self, msg: &str) -> Result<usize> {
    let res = match self.terminal {
      Console::Terminal(ref mut t) => t.write(msg.as_bytes()),
      Console::Pipe(ref mut p) => p.write(msg.as_bytes()),
      Console::Uninitialized => Ok(0),
    };
    self.flush()?;
    res
  }

  // Renders a divider between the logs and action output.
  fn render_divider(&mut self, offset: u16) {
    let cursor_start = self.cursor_start;
    let padding = self.padding.clone();
    let divider = self.divider.clone();

    self
      .write(&format!(
        "{pos}{clear_line}{padding}{blue}{divider}{reset}",
        pos = cursor::Goto(1, cursor_start.1 + offset),
        clear_line = clear::CurrentLine,
        padding = padding,
        blue = color::Fg(color::Blue),
        divider = divider,
        reset = color::Fg(color::Reset)
      ))
      .expect("could not write to terminal");
  }

  // Renders one frame of the log portion of the screen.
  fn render_logs(&mut self, max_entries: usize) -> usize {
    let cursor_start = self.cursor_start;
    let printable_logs: Vec<String> = self.logs.iter().take(max_entries).cloned().collect();

    let mut counter: usize = 0;
    for (n, log_entry) in printable_logs.iter().rev().enumerate() {
      counter += 1;
      let line_shortened_log_entry: String = format!(
        "{padding}{log_entry}",
        padding = self.padding,
        log_entry = log_entry
      )
      .graphemes(true)
      .take(self.terminal_size.0 as usize)
      .collect();

      self
        .write(&format!(
          "{pos}{clear_line}{entry}",
          pos = cursor::Goto(1, cursor_start.1 + n as u16),
          clear_line = clear::CurrentLine,
          entry = line_shortened_log_entry
        ))
        .expect("could not write to terminal");
    }

    if counter > 0 {
      self.render_divider(counter as u16);
      counter += 1;
    }
    counter
  }

  // Renders one frame of the action portion of the screen.
  fn render_actions(&mut self, start_row: usize) {
    let cursor_start = self.cursor_start;
    let worker_states = self.action_map.clone();

    // For every active worker in the action map, jump to the exact cursor
    // representing the swimlane for this worker and lay down a text label.
    for (n, (_worker_id, action)) in worker_states.iter().enumerate() {
      let line_shortened_output: String = format!(
        "{padding}{blue}{sigil}{reset}{action}",
        padding = self.padding,
        blue = color::Fg(color::LightBlue),
        sigil = self.sigil,
        reset = color::Fg(color::Reset),
        action = action
      )
      .graphemes(true)
      // Account for control characters.
      .take(self.terminal_size.0 as usize + 14)
      .collect();

      self
        .write(&format!(
          "{pos}{entry}",
          pos = cursor::Goto(1, cursor_start.1 + start_row as u16 + n as u16),
          entry = line_shortened_output
        ))
        .expect("could not write to terminal");
    }
  }

  // Paints one screen of rendering.
  pub fn render(&mut self) -> std::result::Result<KeyboardCommand, String> {
    if self.suspended {
      return Ok(KeyboardCommand::None);
    }
    self.set_size();
    self.clear();
    let max_log_rows = self.get_max_log_rows();
    let rendered_count = self.render_logs(max_log_rows);
    self.render_actions(rendered_count);
    if let Err(err) = self.flush() {
      return Err(format!("Could not flush terminal: {}", err));
    }
    self.handle_stdin()
  }

  fn handle_stdin(&mut self) -> std::result::Result<KeyboardCommand, String> {
    use termion::event::{parse_event, Event, Key};
    //This buffer must have non-zero size because termion's `read` implementation for
    //AsyncReader will return early without doing anything if it is of length 0.
    //(See https://docs.rs/termion/1.5.4/src/termion/async.rs.html#69 )
    let mut buf: [u8; 32] = [0; 32];

    match self.async_stdin.as_mut().map(|s| s.read(&mut buf)) {
      Some(Ok(0)) | None => Ok(KeyboardCommand::None),
      Some(Ok(_)) => {
        let initial_byte: u8 = buf[0];
        let mut iter = buf[1..].iter().map(|byte| Ok(*byte));
        // TODO: calling `parse_event` in this way means that we will potentially miss keyboard
        // events - a Ctrl-C event has to be the very first event in each `render` frame, or it
        // won't be handled. In practice, the refresh interval is 100 ms, which is fast enough
        // on human timescales that hitting Ctrl-C while the program is running will wind up
        // at the beginning of some frame.  Note that internally termion uses this function
        // in the context of the `next()` function of an Iterator:
        // https://github.com/redox-os/termion/blob/master/src/input.rs .
        let event_or_err = parse_event(initial_byte, &mut iter);
        match event_or_err {
          Ok(Event::Key(Key::Ctrl('c'))) => Ok(KeyboardCommand::CtrlC),
          Err(err) => Err(format!("EngineDisplay keyboard event error: {}", err)),
          _ => Ok(KeyboardCommand::None),
        }
      }
      Some(Err(err)) => Err(format!("EngineDisplay stdin error: {}", err)),
    }
  }

  // Starts the EngineDisplay at the current cursor position.
  pub fn start(&mut self) {
    let write_handle = termion::screen::AlternateScreen::from(stdout());
    self.terminal = match write_handle.into_raw_mode() {
      Ok(t) => Console::Terminal(t),
      Err(_) => Console::Pipe(stdout()),
    };

    self.start_raw_mode().unwrap();
    let cursor_start = self.cursor_start;
    self
      .write(&format!(
        "{hide_cursor}{cursor_init}{clear_after_cursor}",
        hide_cursor = termion::cursor::Hide,
        cursor_init = cursor::Goto(cursor_start.0, cursor_start.1),
        clear_after_cursor = clear::AfterCursor
      ))
      .expect("could not write to terminal");
  }

  // Adds a worker/thread to the visual representation.
  pub fn add_worker(&mut self, worker_name: String) {
    let action_msg = format!("booting {}", worker_name);
    self.update(worker_name, action_msg);
  }

  // Updates the status of a worker/thread.
  pub fn update(&mut self, worker_name: String, action: String) {
    self.action_map.insert(worker_name, action);
  }

  // Removes a worker/thread from the visual representation.
  pub fn remove_worker(&mut self, worker_id: &str) {
    self.action_map.remove(worker_id);
  }

  // Adds a log entry for display.
  pub fn log(&mut self, log_entry: String) {
    self.logs.push_front(log_entry)
  }

  pub fn worker_count(&self) -> usize {
    self.action_map.len()
  }

  pub fn suspend(&mut self) {
    {
      self.terminal = Console::Uninitialized;
      self.suspended = true;
      self.async_stdin = None;
    }
    println!("{}", termion::cursor::Show);
  }

  pub fn unsuspend(&mut self) {
    let write_handle = termion::screen::AlternateScreen::from(stdout());
    self.terminal = match write_handle.into_raw_mode() {
      Ok(t) => Console::Terminal(t),
      Err(_) => Console::Pipe(stdout()),
    };
    self.suspended = false;
    self.async_stdin = Some(async_stdin());
  }

  // Initiates one last screen render, then terminates the EngineDisplay and returns the cursor
  // to a static position, then prints all buffered stdout/stderr output.
  pub fn finish(&mut self) {
    //We don't care about handling the output from render() here, since we're about to shut down
    //the EngineDisplay anyway.
    let _ = self.render();
    {
      self.terminal = Console::Uninitialized; //This forces the AlternateScreen to drop, restoring the original terminal state.
    }

    println!("{}", termion::cursor::Show);
    for log in self.logs.iter() {
      println!("{}", log);
    }
    for PrintableMsg { msg, output } in self.printable_msgs.iter() {
      match output {
        PrintableMsgOutput::Stdout => print!("{}", msg),
        PrintableMsgOutput::Stderr => eprint!("{}", msg),
      }
    }
  }
}
