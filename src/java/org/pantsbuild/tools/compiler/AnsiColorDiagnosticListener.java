// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.compiler;

import java.io.IOException;
import java.io.PrintWriter;
import java.util.Arrays;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import javax.tools.Diagnostic;
import javax.tools.FileObject;

import org.fusesource.jansi.Ansi;
import org.fusesource.jansi.Ansi.Color;
import org.fusesource.jansi.AnsiConsole;

/**
 * A DiagnosticListener that supports colorized console output and warning filters.
 *
 * <p>Users should make sure to call {@link #prepareConsole(boolean)} prior to reporting on any
 * diagnostics.
 *
 * @param <T> The type of FileObject this listener can handle.
 */
class AnsiColorDiagnosticListener<T extends FileObject> extends FilteredDiagnosticListener<T> {
  private static final Pattern EOL = Pattern.compile("$", Pattern.MULTILINE);

  private final PrintWriter outWriter;
  private final PrintWriter errWriter;
  private boolean colorOutput;
  private boolean includeSourceInfo;

  /**
   * Creates a diagnostic listener that outputs notes to {@link System#out} and warnings and errors
   * to {@link System#err}.
   */
  AnsiColorDiagnosticListener() {
    this(new PrintWriter(System.out), new PrintWriter(System.err));
  }

  /**
   * Creates a diagnostic listener that outputs notes to the given {@code outWriter} and warnings
   * and errors to the given {@code errWriter}.
   */
  AnsiColorDiagnosticListener(PrintWriter outWriter, PrintWriter errWriter) {
    this.outWriter = outWriter;
    this.errWriter = errWriter;
  }

  private static String getMessage(Diagnostic<? extends FileObject> diagnostic) {
    return diagnostic.getMessage(Locale.getDefault());
  }

  /**
   * When set to {@code true} this listener will output source and line information in addition to
   * the underlying diagnostic message.
   *
   * @param includeSourceInfo {@code true} to include source and line info.
   */
  void setIncludeSourceInfo(boolean includeSourceInfo) {
    this.includeSourceInfo = includeSourceInfo;
  }

  /**
   * Prepares the console for either plain or color output.  Caller's should make sure to call
   * {@link #releaseConsole()} when they are done reporting diagnostics.
   *
   * @param color {@code true} to output diagnostics in color.
   */
  void prepareConsole(boolean color) {
    colorOutput = color;
    if (color) {
      AnsiConsole.systemInstall();
    } else {
      System.setProperty(Ansi.DISABLE, "true");
    }
  }

  /**
   * Returns the console to its state prior to the last call of {@link #prepareConsole(boolean)}.
   */
  void releaseConsole() {
    if (colorOutput) {
      AnsiConsole.systemUninstall();
    } else {
      System.setProperty(Ansi.DISABLE, "false");
    }
  }

  @Override
  protected void reportOn(Diagnostic<? extends T> diagnostic) {
    switch (diagnostic.getKind()) {
      case NOTE:
        logDiagnostic(outWriter, Ansi.ansi().fg(Color.GREEN), diagnostic);
        break;
      case WARNING:
      case MANDATORY_WARNING:
        logDiagnostic(errWriter, Ansi.ansi().fg(Color.YELLOW), diagnostic);
        break;
      case ERROR:
        logDiagnostic(errWriter, Ansi.ansi().fg(Color.RED), diagnostic);
        break;
      case OTHER:
      default:
        outWriter.println(getMessage(diagnostic));
    }
  }

  private void logDiagnostic(PrintWriter out, Ansi ansi,
      Diagnostic<? extends FileObject> diagnostic) {

    String message = getMessage(diagnostic);
    CharSequence sourceCode = extractSource(diagnostic);
    if (sourceCode == null) {
      out.println(ansi.format("%s%s", includeSourceInfo ? kindMessage(diagnostic) : "", message));
    } else {
      out.println(ansi.format(
          "%s%s\n%s\n%s^",
          includeSourceInfo
              ? String.format("%s:%d: %s",
                              diagnostic.getSource().toUri().getPath(),
                              diagnostic.getLineNumber(),
                              kindMessage(diagnostic))
              : "",
          message,
          sourceCode,
          spaces((int) diagnostic.getColumnNumber() - 1)));
    }
    out.print(Ansi.ansi().reset());
    out.flush();
  }

  private String kindMessage(Diagnostic<? extends FileObject> diagnostic) {
    return String.format("%s: ", diagnostic.getKind().name().toLowerCase());
  }

  private CharSequence extractSource(Diagnostic<? extends FileObject> diagnostic) {
    FileObject source = diagnostic.getSource();
    int startPosition = (int) diagnostic.getStartPosition();
    if ((source == null) || (Diagnostic.NOPOS == startPosition) || (startPosition < 1)) {
      return null;
    }
    try {
      CharSequence content = source.getCharContent(true);
      // Start and end positions can both be in the middle of a line, here we expand out and grab
      // The whole line for useful error context.
      Matcher matcher = EOL.matcher(content);
      int endPosition =  (int) diagnostic.getEndPosition();
      if (matcher.find(startPosition)) {
        endPosition = matcher.end();
      }

      // Handle the error being at eol - back up a step so we can scan back to the prior eol and
      // capture the line of program text preceding the error point at eol.
      if (startPosition == endPosition && startPosition > 0) {
        startPosition--;
      }

      for (; startPosition > 0; startPosition--) {
        if (content.charAt(startPosition) == '\n' || content.charAt(startPosition) == '\r') {
          // Start just after the beginning newline
          startPosition++;
          break;
        }
      }
      return content.subSequence(startPosition, endPosition);
    } catch (IOException e) {
      return null;
    } catch (IndexOutOfBoundsException e) {
      return null;
    }
  }

  private String spaces(int count) {
    char[] spaces = new char[count];
    Arrays.fill(spaces, ' ');
    return new String(spaces);
  }
}
