extern crate rand;
extern crate termion;
extern crate unicode_segmentation;

use std::collections::{BTreeMap, VecDeque};
use std::io::Write;
use std::io::{stdout, Result, Stdout};
use std::thread;
use std::time::Duration;

use termion::cursor::DetectCursorPos;
use termion::raw::IntoRawMode;
use termion::raw::RawTerminal;
use termion::{clear, color, cursor};
use unicode_segmentation::UnicodeSegmentation;

enum Console {
  Terminal(RawTerminal<Stdout>),
  Pipe(Stdout),
}

pub struct EngineDisplay {
  sigil: char,
  divider: String,
  poll_interval_ms: Duration,
  padding: String,
  terminal: Console,
  action_map: BTreeMap<String, String>,
  logs: VecDeque<String>,
  running: bool,
  is_tty: bool,
  cursor_start: (u16, u16),
  terminal_size: (u16, u16),
}

// TODO: Prescribe a threading/polling strategy for callers - or implement a built-in one.
// TODO: Better error handling for .flush() and .write() failure modes.
// TODO: Permit scrollback in the terminal - both at exit and during the live run.
impl EngineDisplay {
  pub fn for_stdout(indent_level: u16) -> EngineDisplay {
    let write_handle = stdout();
    let is_tty = termion::is_tty(&write_handle);

    EngineDisplay {
      sigil: '⚡',
      divider: "▵".to_string(),
      poll_interval_ms: Duration::from_millis(55),
      padding: " ".repeat(indent_level.into()),
      terminal: if !is_tty {
        Console::Pipe(write_handle)
      } else {
        match write_handle.into_raw_mode() {
          Ok(t) => Console::Terminal(t),
          Err(_) => Console::Pipe(stdout()),
        }
      },
      action_map: BTreeMap::new(),
      // This is arbitrary based on a guesstimated peak terminal row size for modern displays.
      // The reason this can't be capped to e.g. the starting size is because of resizing - we
      // want to be able to fill the entire screen if resized much larger than when we started.
      logs: VecDeque::with_capacity(500),
      running: false,
      is_tty: is_tty,
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
    }
  }

  // Gets the current terminal's cursor position, if applicable.
  fn get_cursor_pos(&mut self) -> (u16, u16) {
    match self.terminal {
      // N.B. Real TTY coordinates start at (1, 1).
      Console::Terminal(ref mut t) => t.cursor_pos().unwrap_or((0, 0)),
      Console::Pipe(_) => (0, 0),
    }
  }

  // Gets the current terminal's width and height, if applicable.
  fn get_size() -> (u16, u16) {
    termion::terminal_size().unwrap_or((0, 0))
  }

  // Whether or not the EngineDisplay is running (whether .start() has been called).
  pub fn is_running(&self) -> bool {
    self.running
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
    }
  }

  // Writes output to the terminal.
  fn write(&mut self, msg: &str) -> Result<usize> {
    match self.terminal {
      Console::Terminal(ref mut t) => t.write(msg.as_bytes()),
      Console::Pipe(ref mut p) => p.write(msg.as_bytes()),
    }
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
      ).graphemes(true)
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
          padding=self.padding,
          blue=color::Fg(color::LightBlue),
          sigil=self.sigil,
          reset=color::Fg(color::Reset),
          action=action
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

  fn render_for_pipe(&self) {
    // TODO: Handle non-tty output w polling interval adjustment + summary rendering.
    panic!("TODO");
  }

  // Paints one screen of rendering.
  fn render_for_tty(&mut self) {
    self.set_size();
    self.clear();
    let max_log_rows = self.get_max_log_rows();
    let rendered_count = self.render_logs(max_log_rows);
    self.render_actions(rendered_count);
    self.flush().expect("could not flush terminal!");
  }

  // Paints one screen of rendering.
  pub fn render(&mut self) {
    // TODO: Split this fork out into sub-types of EngineDisplay.
    match self.is_tty {
      true => self.render_for_tty(),
      false => self.render_for_pipe(),
    }
  }

  // Paints one screen of rendering and sleeps for the poll interval.
  pub fn render_and_sleep(&mut self) {
    self.render();
    thread::sleep(self.poll_interval_ms);
  }

  // Starts the EngineDisplay at the current cursor position.
  pub fn start(&mut self) {
    self.running = true;
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

  // Terminates the EngineDisplay and returns the cursor to a static position.
  pub fn finish(&mut self) {
    self.running = false;
    let current_pos = self.get_cursor_pos();
    let action_count = self.action_map.len() as u16;
    self
      .write(&format!(
        "{park_cursor}{clear_after_cursor}{reveal_cursor}",
        park_cursor = cursor::Goto(1, current_pos.1 - action_count),
        clear_after_cursor = clear::AfterCursor,
        reveal_cursor = termion::cursor::Show
      ))
      .expect("could not write to terminal");
  }
}
