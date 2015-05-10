package org.pantsbuild.tools.compiler;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;
import java.util.regex.Pattern;

import javax.annotation.Nullable;
import javax.tools.Diagnostic;
import javax.tools.Diagnostic.Kind;
import javax.tools.FileObject;

import com.google.common.collect.ImmutableList;
import com.google.common.reflect.TypeToken;

import org.easymock.EasyMock;
import org.junit.Test;

import org.pantsbuild.testing.EasyMockTest;
import org.pantsbuild.tools.compiler.DiagnosticFilters.DiagnosticFilter;
import org.pantsbuild.tools.compiler.DiagnosticFilters.Guard;
import org.pantsbuild.tools.compiler.DiagnosticFilters.Treatment;

import static org.easymock.EasyMock.expect;

import static org.junit.Assert.assertEquals;

public class DiagnosticFiltersTest extends EasyMockTest {

  @Test
  public void testIgnorePathPrefixes() throws URISyntaxException {
    Diagnostic<FileObject> a = expectDiagnosticUri("file:///a");
    Diagnostic<FileObject> b = expectDiagnosticUri("file:///b");
    Diagnostic<FileObject> c = expectDiagnosticUri("file:///c");
    control.replay();

    DiagnosticFilter<FileObject> filter =
        DiagnosticFilters.ignorePathPrefixes(ImmutableList.of("/a", "/b"));

    assertEquals(Treatment.IGNORE, filter.categorize(a));
    assertEquals(Treatment.IGNORE, filter.categorize(b));
    assertEquals(Treatment.PASS, filter.categorize(c));
  }

  private Diagnostic<FileObject> expectDiagnosticUri(String uri) throws URISyntaxException {
    return expectDiagnostic(Kind.WARNING, new URI(uri), null);
  }

  @Test
  public void testIgnoreMessagesMatching() throws URISyntaxException {
    Diagnostic<FileObject> a = expectDiagnosticMessage("fred jake*");
    Diagnostic<FileObject> b = expectDiagnosticMessage("*fred jake");
    Diagnostic<FileObject> c = expectDiagnosticMessage("*fred jake*");
    control.replay();

    DiagnosticFilter<FileObject> filter =
        DiagnosticFilters.ignoreMessagesMatching(
            ImmutableList.of(Pattern.compile("^fred.*"), Pattern.compile(".*jake$")));

    assertEquals(Treatment.IGNORE, filter.categorize(a));
    assertEquals(Treatment.IGNORE, filter.categorize(b));
    assertEquals(Treatment.PASS, filter.categorize(c));
  }

  private Diagnostic<FileObject> expectDiagnosticMessage(String message) throws URISyntaxException {
    return expectDiagnostic(Kind.WARNING, null, message);
  }

  @Test
  public void testCombine() throws URISyntaxException {
    Diagnostic<FileObject> a = expectDiagnostic(Kind.WARNING, new URI("file:///a"), null);
    Diagnostic<FileObject> b = expectDiagnostic(Kind.ERROR, new URI("file:///b"), "fred*");
    Diagnostic<FileObject> c = expectDiagnostic(Kind.WARNING, new URI("file:///c"), "*fred");
    control.replay();

    DiagnosticFilter<FileObject> filter =
        DiagnosticFilters.combine(
            ImmutableList.of(
                DiagnosticFilters.ignorePathPrefixes(ImmutableList.of("/a")),
                DiagnosticFilters.ignoreMessagesMatching(
                    ImmutableList.of(Pattern.compile("^fred.*")))));


    assertEquals(Treatment.IGNORE, filter.categorize(a));
    assertEquals(Treatment.IGNORE, filter.categorize(b));
    assertEquals(Treatment.WARNING, filter.categorize(c));
  }

  @Test
  public void testGuarded() throws URISyntaxException {
    Diagnostic<FileObject> a = expectDiagnostic(Kind.NOTE, new URI("file:///a"), null);

    // URI testing should short-circuit on the kind test
    Diagnostic<FileObject> b = expectDiagnostic(Kind.WARNING, null, null);

    Diagnostic<FileObject> c = expectDiagnostic(Kind.NOTE, new URI("file:///c"), null);

    control.replay();

    DiagnosticFilter<FileObject> filter =
        DiagnosticFilters.guarded(DiagnosticFilters.ignorePathPrefixes(ImmutableList.of("/a")),
            new Guard<Diagnostic<? extends FileObject>>() {
              @Override public boolean permit(Diagnostic<? extends FileObject> diagnostic) {
                return diagnostic.getKind() == Kind.NOTE;
              }
            });

    assertEquals(Treatment.IGNORE, filter.categorize(a));
    assertEquals(Treatment.PASS, filter.categorize(b));
    assertEquals(Treatment.PASS, filter.categorize(c));
  }

  private Diagnostic<FileObject> expectDiagnostic(Kind kind, @Nullable URI uri,
      @Nullable String message) throws URISyntaxException {
    Diagnostic<FileObject> diagnostic = createMock(new TypeToken<Diagnostic<FileObject>>() { });
    expect(diagnostic.getKind()).andReturn(kind).anyTimes();
    if (uri != null) {
      FileObject fileObject = createMock(FileObject.class);
      expect(fileObject.toUri()).andReturn(uri).atLeastOnce();
      expect(diagnostic.getSource()).andReturn(fileObject);
    }
    if (message != null) {
      expect(diagnostic.getMessage(EasyMock.<Locale>notNull())).andReturn(message).atLeastOnce();
    }
    return diagnostic;
  }
}
