package org.pantsbuild.tools.compiler;

import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.util.Arrays;
import java.util.Locale;
import java.util.regex.Pattern;

import javax.annotation.Nullable;
import javax.tools.Diagnostic;
import javax.tools.Diagnostic.Kind;
import javax.tools.FileObject;

import com.google.common.base.Splitter;
import com.google.common.collect.ImmutableList;
import com.google.common.reflect.TypeToken;
import com.google.common.testing.TearDown;

import org.easymock.EasyMock;
import org.junit.Before;
import org.junit.Test;
import org.pantsbuild.testing.EasyMockTest;

import static org.easymock.EasyMock.anyBoolean;
import static org.easymock.EasyMock.expect;

import static org.junit.Assert.assertEquals;

public class AnsiColorDiagnosticListenerTest extends EasyMockTest {
  private static final Pattern NEWLINE = Pattern.compile("\r?\n", Pattern.MULTILINE);

  private AnsiColorDiagnosticListener<FileObject> listener;
  private Diagnostic<FileObject> diagnostic;
  private FileObject file;
  private StringWriter out;
  private StringWriter err;

  @Before
  public void setUp() {
    out = new StringWriter();
    err = new StringWriter();

    listener = new AnsiColorDiagnosticListener<FileObject>(
        new PrintWriter(out), new PrintWriter(err));
    listener.prepareConsole(false);
    addTearDown(new TearDown() {
      @Override public void tearDown() {
        listener.releaseConsole();
      }
    });

    diagnostic = createMock(new TypeToken<Diagnostic<FileObject>>() { });
    file = createMock(FileObject.class);
  }

  @Test
  public void testNote() throws IOException {
    expectDiagnostic(Kind.NOTE, "aside", null, Diagnostic.NOPOS, Diagnostic.NOPOS,
        Diagnostic.NOPOS);

    control.replay();
    listener.reportOn(diagnostic);

    assertOut("aside");
    assertNoErr();
  }

  @Test
  public void testOther() throws IOException {
    expectDiagnostic(Kind.OTHER, "unknown", null, Diagnostic.NOPOS, Diagnostic.NOPOS,
        Diagnostic.NOPOS);

    control.replay();
    listener.reportOn(diagnostic);

    assertOut("unknown");
    assertNoErr();
  }

  @Test
  public void testWarning() throws IOException {
    expectDiagnostic(Kind.WARNING, "warning", "abcdefg", 1L, 3L, 2L);

    control.replay();
    listener.reportOn(diagnostic);

    assertErr(
        "warning",
        "abcdefg",
        " ^");
    assertNoOut();
  }

  @Test
  public void testMandatoryWarning() throws IOException {
    expectDiagnostic(Kind.MANDATORY_WARNING, "mandatory warning", "abcdefg", 1L, 5L, 1L);

    control.replay();
    listener.reportOn(diagnostic);

    assertErr(
        "mandatory warning",
        "abcdefg",
        "^");
    assertNoOut();
  }

  @Test
  public void testError() throws IOException {
    expectDiagnostic(Kind.ERROR, "error", "a\nbcd\nefg", 3L, 5L, 2L);

    control.replay();
    listener.reportOn(diagnostic);

    assertErr(
        "error",
        "bcd",
        " ^");
    assertNoOut();
  }

  @Test
  public void testErrorEol() throws IOException {
    expectDiagnostic(Kind.ERROR, "error", "a\nbcd\n", 5L, 6L, 4L);

    control.replay();
    listener.reportOn(diagnostic);

    assertErr(
        "error",
        "bcd",
        "   ^");
    assertNoOut();
  }

  private void assertOut(String... lines) {
    assertOutput(out, Arrays.asList(lines));
  }

  private void assertErr(String... lines) {
    assertOutput(err, Arrays.asList(lines));
  }

  private void assertOutput(StringWriter writer, Iterable<String> lines) {
    assertEquals(ImmutableList.builder().addAll(lines).add("").build(),
        ImmutableList.copyOf(Splitter.on(NEWLINE).split(writer.toString())));
  }

  private void assertNoOut() {
    assertNoOutput(out);
  }

  private void assertNoErr() {
    assertNoOutput(err);
  }

  private void assertNoOutput(StringWriter writer) {
    assertEquals("", writer.toString());
  }

  private void expectDiagnostic(Kind kind, String message, @Nullable String source, long start,
      long end, long col) throws IOException {

    expect(diagnostic.getKind()).andReturn(kind);
    expect(diagnostic.getMessage(EasyMock.<Locale>notNull())).andReturn(message);
    expect(diagnostic.getSource()).andReturn(file).anyTimes();
    expect(diagnostic.getStartPosition()).andReturn(start).anyTimes();
    expect(diagnostic.getEndPosition()).andReturn(end).anyTimes();
    expect(diagnostic.getColumnNumber()).andReturn(col).anyTimes();
    expect(file.getCharContent(anyBoolean())).andReturn(source).anyTimes();
  }
}
