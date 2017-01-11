// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.jar;

import com.google.common.base.Charsets;
import com.google.common.base.Function;
import com.google.common.base.Optional;
import com.google.common.base.Predicate;
import com.google.common.collect.FluentIterable;
import com.google.common.collect.ImmutableList;
import com.google.common.collect.Iterables;
import com.google.common.io.ByteSource;
import com.google.common.io.ByteStreams;
import com.google.common.io.Closer;
import com.google.common.io.Files;
import com.google.common.reflect.TypeToken;
import com.google.common.testing.TearDown;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.jar.Attributes.Name;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.Manifest;
import java.util.regex.Pattern;
import org.easymock.Capture;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.junit.runners.Parameterized;
import org.junit.runners.Parameterized.Parameters;
import org.pantsbuild.testing.EasyMockTest;
import org.pantsbuild.testing.TearDownTestCase;
import org.pantsbuild.tools.jar.JarBuilder.DuplicateAction;
import org.pantsbuild.tools.jar.JarBuilder.DuplicateEntryException;
import org.pantsbuild.tools.jar.JarBuilder.DuplicateHandler;
import org.pantsbuild.tools.jar.JarBuilder.DuplicatePolicy;
import org.pantsbuild.tools.jar.JarBuilder.Entry;
import org.pantsbuild.tools.jar.JarBuilder.Listener;

import static org.easymock.EasyMock.capture;
import static org.easymock.EasyMock.createMock;
import static org.easymock.EasyMock.eq;
import static org.easymock.EasyMock.expect;
import static org.easymock.EasyMock.newCapture;
import static org.easymock.EasyMock.replay;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

public class JarBuilderTest {
  interface ExceptionalClosure<T, E extends Exception> {
    void execute(T input) throws E;
  }

  interface ExceptionalFunction<S, T, E extends Exception> {
    T apply(S input) throws E;
  }

  public static class DuplicatePolicyTests {

    public static class DelegateTest extends EasyMockTest {
      @Test
      public void testPassDelegates() {
        Predicate<CharSequence> predicate =
            createMock(new TypeToken<Predicate<CharSequence>>() { });
        expect(predicate.apply("foo")).andReturn(true);
        expect(predicate.apply("foo")).andReturn(false);
        control.replay();

        DuplicatePolicy policy = new DuplicatePolicy(predicate, DuplicateAction.REPLACE);

        assertEquals(DuplicateAction.REPLACE, policy.getAction());
        assertTrue(policy.apply("foo"));
        assertFalse(policy.apply("foo"));
      }
    }

    public static class MatchesTest {
      @Test
      public void test() {
        DuplicatePolicy anyA = DuplicatePolicy.pathMatches("a", DuplicateAction.CONCAT);
        DuplicatePolicy anyTextA = DuplicatePolicy.pathMatches("a", DuplicateAction.CONCAT_TEXT);
        DuplicatePolicy startA = DuplicatePolicy.pathMatches("^a", DuplicateAction.SKIP);
        DuplicatePolicy endA = DuplicatePolicy.pathMatches("a$", DuplicateAction.REPLACE);
        DuplicatePolicy exactlyA = DuplicatePolicy.pathMatches("^a$", DuplicateAction.THROW);

        assertEquals(DuplicateAction.CONCAT, anyA.getAction());
        assertEquals(DuplicateAction.CONCAT_TEXT, anyTextA.getAction());
        assertEquals(DuplicateAction.SKIP, startA.getAction());
        assertEquals(DuplicateAction.REPLACE, endA.getAction());
        assertEquals(DuplicateAction.THROW, exactlyA.getAction());

        assertTrue(anyA.apply("bab"));
        assertTrue(anyA.apply("ab"));
        assertTrue(anyA.apply("ba"));
        assertFalse(anyA.apply("bbb"));

        assertTrue(anyTextA.apply("bab"));
        assertTrue(anyTextA.apply("ab"));
        assertTrue(anyTextA.apply("ba"));
        assertFalse(anyTextA.apply("bbb"));

        assertTrue(startA.apply("ab"));
        assertTrue(startA.apply("aa"));
        assertFalse(startA.apply("bab"));
        assertFalse(startA.apply("ba"));

        assertTrue(endA.apply("ba"));
        assertTrue(endA.apply("aa"));
        assertFalse(endA.apply("bab"));
        assertFalse(endA.apply("ab"));

        assertTrue(exactlyA.apply("a"));
        assertFalse(exactlyA.apply("aa"));
        assertFalse(exactlyA.apply("b"));
      }
    }
  }

  public static class DuplicateHandlerTests {

    @RunWith(Parameterized.class)
    public static class AlwaysTest {

      @Parameters
      public static Collection<Object[]> data() {
        return FluentIterable.from(ImmutableList.copyOf(DuplicateAction.values()))
            .transform(new Function<DuplicateAction, Object[]>() {
              @Override public Object[] apply(DuplicateAction item) {
                return new Object[]{item};
              }
            }).toList();
      }

      private final DuplicateAction action;

      public AlwaysTest(DuplicateAction action) {
        this.action = action;
      }

      @Test
      public void test() {
        DuplicateHandler always = DuplicateHandler.always(action);
        assertEquals(action, always.actionFor("a"));
        assertEquals(action, always.actionFor("b"));
        assertEquals(action, always.actionFor("dalek"));
      }
    }

    public static class DuplicateHandlerTest extends EasyMockTest {
      @Test
      public void test() {
        Predicate<CharSequence> predicate1 =
            createMock(new TypeToken<Predicate<CharSequence>>() { });
        Predicate<CharSequence> predicate2 =
            createMock(new TypeToken<Predicate<CharSequence>>() { });

        // test1
        expect(predicate1.apply("a")).andReturn(true);

        // test2
        expect(predicate1.apply("a")).andReturn(false);
        expect(predicate2.apply("a")).andReturn(true);

        // test3
        expect(predicate1.apply("a")).andReturn(false);
        expect(predicate2.apply("a")).andReturn(false);

        control.replay();

        DuplicatePolicy policy1 = new DuplicatePolicy(predicate1, DuplicateAction.CONCAT);
        DuplicatePolicy policy2 = new DuplicatePolicy(predicate2, DuplicateAction.REPLACE);
        DuplicateHandler handler = new DuplicateHandler(DuplicateAction.THROW, policy1, policy2);

        assertEquals(DuplicateAction.CONCAT, handler.actionFor("a"));
        assertEquals(DuplicateAction.REPLACE, handler.actionFor("a"));
        assertEquals(DuplicateAction.THROW, handler.actionFor("a"));
      }
    }
  }

  public static class WriteTestBase extends TearDownTestCase {

    protected static ByteSource content(String content) {
      return ByteSource.wrap(content.getBytes(Charsets.UTF_8));
    }

    protected static String content(ByteSource content) throws IOException {
      return new String(content.read(), Charsets.UTF_8);
    }

    @Rule
    public TemporaryFolder temporary = new TemporaryFolder();

    private Closer tearDownCloser;

    @Before
    public void setUpCloser() {
      tearDownCloser = Closer.create();
      addTearDown(new TearDown() {
        @Override public void tearDown() throws IOException {
          tearDownCloser.close();
        }
      });
    }

    protected File newFile() throws IOException {
      File file = temporary.newFile();
      Files.touch(file);
      return file;
    }

    protected File newFile(String name) throws IOException {
      File file = new File(newFolder(), name);
      Files.touch(file);
      return file;
    }

    protected File newFolder(String path) throws IOException {
      return new File(newFolder(), path);
    }

    protected File newFolder() throws IOException {
      return temporary.newFolder();
    }

    protected JarBuilder jarBuilder() throws IOException {
      return jarBuilder(newFile());
    }

    protected JarBuilder jarBuilder(File destinationJar) {
      return jarBuilder(destinationJar, Listener.NOOP);
    }

    protected JarBuilder jarBuilder(File destinationJar, Listener listener) {
      return tearDownCloser.register(new JarBuilder(destinationJar, listener));
    }

    protected void write(File file, String contents) throws IOException {
      Files.createParentDirs(file);
      Files.write(contents, file, Charsets.UTF_8);
    }
  }

  @SuppressWarnings("FunctionalInterfaceClash")
  public static class WriteTest extends WriteTestBase {
    private static void assertListing(JarFile jar, String... paths) {
      assertListing(jar, Arrays.asList(paths), true);
    }

    private static void assertListingUnordered(JarFile jar, String... paths) {
      assertListing(jar, Arrays.asList(paths), false);
    }

    private static final ImmutableList<String> CONSTANT_ENTRIES =
        ImmutableList.of("META-INF/", "META-INF/MANIFEST.MF");

    private static void assertListing(JarFile jar, Iterable<String> paths, boolean ordered) {
      FluentIterable<String> expectedEntries =
          FluentIterable.from(Iterables.concat(CONSTANT_ENTRIES, paths));
      Collection<String> expected = ordered ? expectedEntries.toList() : expectedEntries.toSet();

      FluentIterable<String> actualEntries = FluentIterable.from(Collections.list(jar.entries()))
          .transform(new Function<JarEntry, String>() {
            @Override public String apply(JarEntry entry) {
              return entry.getName();
            }
          });
      Collection<String> actual = ordered ? actualEntries.toList() : actualEntries.toSet();

      assertEquals(expected, actual);
    }

    private void doWithJar(File path, final ExceptionalClosure<JarFile, IOException> work)
        throws IOException {

      doWithJar(path, new ExceptionalFunction<JarFile, Void, IOException>() {
        @Override public Void apply(JarFile jar) throws IOException {
          work.execute(jar);
          return null;
        }
      });
    }

    private <T> T doWithJar(File path, ExceptionalFunction<JarFile, T, IOException> work)
        throws IOException {

      Closer closer = Closer.create();
      JarFile jar = JarFileUtil.openJarFile(closer, path);
      try {
        return work.apply(jar);
      } catch (IOException e) {
        throw closer.rethrow(e);
      } finally {
        closer.close();
      }
    }

    private void assertCompressedContents(
        JarFile jar,
        String path,
        String expectedContent)
        throws IOException {

      assertContents(jar, path, expectedContent, true /* compressed */);
    }

    private void assertStoredContents(
        JarFile jar,
        String path,
        String expectedContent)
        throws IOException {

      assertContents(jar, path, expectedContent, false /* compressed */);
    }

    private void assertContents(
        JarFile jar,
        String path,
        String expectedContent,
        boolean compressed)
        throws IOException {

      Closer closer = Closer.create();
      JarEntry jarEntry = jar.getJarEntry(path);
      int method = jarEntry.getMethod();
      if (!compressed) {
        assertEquals(JarEntry.STORED, method);
      } else {
        assertTrue(method == JarEntry.STORED || method == JarEntry.DEFLATED);
      }
      InputStream entryIn = closer.register(jar.getInputStream(jarEntry));
      try {
        assertEquals(expectedContent, new String(ByteStreams.toByteArray(entryIn), Charsets.UTF_8));
      } catch (IOException e) {
        throw closer.rethrow(e);
      } finally {
        closer.close();
      }
    }

    @Test
    public void testEmpty() throws IOException {
      File builtJar = jarBuilder().write();

      doWithJar(builtJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override
        public void execute(JarFile created) throws IOException {
          assertListing(created);
        }
      });
    }

    @Test
    public void testCustomManifestCreate() throws IOException {
      final Manifest customManifest = new Manifest();
      customManifest.getMainAttributes().put(Name.MANIFEST_VERSION, "1.0");

      File destinationJar = jarBuilder().useCustomManifest(customManifest).write();

      doWithJar(destinationJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override public void execute(JarFile created) throws IOException {
          assertListing(created);
          assertEquals(customManifest, created.getManifest());
        }
      });
    }

    @Test
    public void testCustomManifestUpdate() throws IOException {
      Manifest initial = new Manifest();
      initial.getMainAttributes().put(Name.MANIFEST_VERSION, "1.0");
      initial.getMainAttributes().put(Name.MAIN_CLASS, "com.bob.Tool");

      File destinationJar = jarBuilder().useCustomManifest(initial).write();

      final Manifest manifest = doWithJar(destinationJar,
          new ExceptionalFunction<JarFile, Manifest, IOException>() {
            @Override public Manifest apply(JarFile created) throws IOException {
              assertListing(created);
              return created.getManifest();
            }
          });

      final Manifest customManifest = new Manifest();
      customManifest.getMainAttributes().put(Name.MANIFEST_VERSION, "1.0");
      customManifest.getMainAttributes().put(Name.MAIN_CLASS, "com.john.Tool");

      jarBuilder(destinationJar).useCustomManifest(customManifest).write();

      doWithJar(destinationJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override public void execute(JarFile updated) throws IOException {
          assertListing(updated);
          Manifest updatedManifest = updated.getManifest();
          assertFalse(manifest.equals(updatedManifest));
          assertEquals(customManifest, updatedManifest);
        }
      });
    }

    @Test
    public void testAddFile() throws IOException {
      File destinationJar = jarBuilder().add(content("42"), "meaning/of/life").write();

      doWithJar(destinationJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override public void execute(JarFile jar) throws IOException {
          assertListing(jar, "meaning/", "meaning/of/", "meaning/of/life");
          assertStoredContents(jar, "meaning/of/life", "42");
        }
      });
    }

    @Test
    public void testAddDirectory() throws IOException {
      File dir = newFolder("life/of/brian");
      write(new File(dir, "is"), "42");
      write(new File(dir, "used/to/be"), "1/137");

      File destinationJar = jarBuilder()
          .addDirectory(dir, Optional.<String>absent())
          .addDirectory(dir, Optional.of("meaning/of/life"))
          .write();

      doWithJar(destinationJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override public void execute(JarFile jar) throws IOException {
          assertListingUnordered(jar,
              "is",
              "used/",
              "used/to/",
              "used/to/be",
              "meaning/",
              "meaning/of/",
              "meaning/of/life/",
              "meaning/of/life/is",
              "meaning/of/life/used/",
              "meaning/of/life/used/to/",
              "meaning/of/life/used/to/be");
          assertStoredContents(jar, "is", "42");
          assertStoredContents(jar, "used/to/be", "1/137");
          assertStoredContents(jar, "meaning/of/life/is", "42");
          assertStoredContents(jar, "meaning/of/life/used/to/be", "1/137");
        }
      });
    }

    @Test
    public void testAddDirectoryManifestIgnored() throws IOException {
      File dir = newFolder();
      File manifestFile = new File(dir, JarFile.MANIFEST_NAME);
      write(manifestFile, String.format("%s: %s", Name.MAIN_CLASS, "some.main.class"));

      // Manifest entry should be filtered for "/path/to/META-INF/=META-INF/".
      File destinationJar = jarBuilder()
          .addDirectory(manifestFile.getParentFile(), Optional.of("META-INF"))
          .write();

      doWithJar(destinationJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override
        public void execute(JarFile jar) throws IOException {
          // Default manifest is still generated.
          assertListingUnordered(jar);
        }
      });

    }

    @Test
    public void testAddJar() throws IOException {
      File sourceJar = jarBuilder().add(content("1/137"), "meaning/of/the/universe").write();

      File destinationJar =
          jarBuilder()
              .add(content("42"), "meaning/of/life")
              .addJar(sourceJar)
              .write();

      doWithJar(destinationJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override public void execute(JarFile jar) throws IOException {
          assertListing(jar,
              "meaning/",
              "meaning/of/",
              "meaning/of/life",
              "meaning/of/the/",
              "meaning/of/the/universe");
          assertStoredContents(jar, "meaning/of/life", "42");
          assertStoredContents(jar, "meaning/of/the/universe", "1/137");
        }
      });
    }

    @Test
    public void testSkip() throws IOException {
      File dir = newFolder("life/of/brian");
      write(new File(dir, "is"), "42");
      write(new File(dir, "used/to/be"), "4");

      File sourceJar =
          jarBuilder()
              .add(content("1/137"), "meaning/of/the/universe")
              .add(content("fine structure constant"), "meaning/of/the/universe/README")
              .write();

      File destinationJar =
          jarBuilder()
              .add(content("43"), "meaning/of/life/isn't")
              .addDirectory(dir, Optional.of("meaning/of/life"))
              .addJar(sourceJar)
              .write(
                  true, // compress
                  DuplicateHandler.always(DuplicateAction.THROW),
                  Pattern.compile("is$"),
                  Pattern.compile("/README"));

      doWithJar(destinationJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override public void execute(JarFile jar) throws IOException {
          assertListing(jar,
              "meaning/",
              "meaning/of/",
              "meaning/of/life/",
              "meaning/of/life/isn't",
              "meaning/of/life/used/",
              "meaning/of/life/used/to/",
              "meaning/of/life/used/to/be",
              "meaning/of/the/",
              "meaning/of/the/universe");
          assertCompressedContents(jar, "meaning/of/life/isn't", "43");
          assertCompressedContents(jar, "meaning/of/life/used/to/be", "4");
          assertCompressedContents(jar, "meaning/of/the/universe", "1/137");
        }
      });
    }

    @Test
    public void testPolicyConcat() throws IOException {
      DuplicateHandler alwaysConcat = DuplicateHandler.always(DuplicateAction.CONCAT);

      File destinationJar = jarBuilder().add(content("1/137\n"), "meaning/of/life").write();

      jarBuilder(destinationJar)
          .add(content("42\n"), "meaning/of/life")
          .add(content("jake\n"), "meaning/of/life")
          .write(true /* compress */, alwaysConcat);

      File jar = jarBuilder().add(content("more\n"), "meaning/of/life").write();

      File dir = newFolder("life/of");
      write(new File(dir, "life"), "jane");

      jarBuilder(destinationJar)
          .addJar(jar)
          .addDirectory(dir, Optional.of("meaning/of"))
          .write(true /* compress */, alwaysConcat);

      doWithJar(destinationJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override public void execute(JarFile jar) throws IOException {
          assertListing(jar,
              "meaning/",
              "meaning/of/",
              "meaning/of/life");
          assertCompressedContents(jar, "meaning/of/life", "1/137\n42\njake\nmore\njane");
        }
      });
    }

    @Test
    public void testPolicyConcatText() throws IOException {
      DuplicateHandler alwaysConcat = DuplicateHandler.always(DuplicateAction.CONCAT_TEXT);

      File destinationJar = jarBuilder().add(content("1/137"), "meaning/of/life").write();

      jarBuilder(destinationJar)
          .add(content("42"), "meaning/of/life")
          .add(content(""), "meaning/of/life")
          .add(content("jake\n"), "meaning/of/life")
          .write(true /* compress */, alwaysConcat);

      File jar = jarBuilder().add(content("more\n"), "meaning/of/life").write();

      File dir = newFolder("life/of");
      write(new File(dir, "life"), "jane");

      jarBuilder(destinationJar)
          .addJar(jar)
          .addDirectory(dir, Optional.of("meaning/of"))
          .write(true /* compress */, alwaysConcat);

      doWithJar(destinationJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override public void execute(JarFile jar) throws IOException {
          assertListing(jar,
              "meaning/",
              "meaning/of/",
              "meaning/of/life");
          assertCompressedContents(jar, "meaning/of/life", "1/137\n42\njake\nmore\njane\n");
        }
      });
    }

    @Test
    public void testPolicySkip() throws IOException {
      DuplicateHandler alwaysSkip = DuplicateHandler.always(DuplicateAction.SKIP);

      File destinationJar =
          jarBuilder()
              .add(content("1/137"), "meaning/of/life")
              .add(content("!"), "meaning/of/life")
              .write(true /* compress */, alwaysSkip);

      jarBuilder(destinationJar)
          .addJar(destinationJar)
          .add(content("42"), "meaning/of/life")
          .write(true /* compress */, alwaysSkip);

      doWithJar(destinationJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override public void execute(JarFile jar) throws IOException {
          assertListing(jar,
              "meaning/",
              "meaning/of/",
              "meaning/of/life");
          assertCompressedContents(jar, "meaning/of/life", "1/137");
        }
      });
    }

    @Test
    public void testPolicyReplace() throws IOException {
      DuplicateHandler replaceMeaningOfLife =
          new DuplicateHandler(DuplicateAction.SKIP,
              DuplicatePolicy.pathMatches("^meaning/of/life$", DuplicateAction.REPLACE));

      File destinationJar =
          jarBuilder()
              .add(content("1/137"), "meaning/of/life")
              .add(content("!"), "meaning/of/life")
              .add(content("1/137"), "meaning/of/brian")
              .write(false /* compress */, replaceMeaningOfLife);

      doWithJar(destinationJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override public void execute(JarFile jar) throws IOException {
          assertListing(jar,
              "meaning/",
              "meaning/of/",
              "meaning/of/life",
              "meaning/of/brian");
          assertStoredContents(jar, "meaning/of/life", "!");
          assertStoredContents(jar, "meaning/of/brian", "1/137");
        }
      });

      jarBuilder(destinationJar)
          .add(content("42"), "meaning/of/life")
          .add(content("jane"), "meaning/of/life")
          .write(true /* compress */, replaceMeaningOfLife);

      doWithJar(destinationJar, new ExceptionalClosure<JarFile, IOException>() {
        @Override public void execute(JarFile jar) throws IOException {
          assertListing(jar,
              "meaning/",
              "meaning/of/",
              "meaning/of/life",
              "meaning/of/brian");
          assertCompressedContents(jar, "meaning/of/life", "jane");
          assertCompressedContents(jar, "meaning/of/brian", "1/137");
        }
      });
    }

    @Test
    public void testPolicyThrowPreExisting() throws IOException {
      DuplicateHandler alwaysThrow = DuplicateHandler.always(DuplicateAction.THROW);
      File destinationJar = jarBuilder().add(content("1/137"), "meaning/of/life").write();

      JarBuilder jarBuilder = jarBuilder(destinationJar).add(content("42"), "meaning/of/life");
      try {
        jarBuilder.write(true /* compress */, alwaysThrow);
        fail("Expected jar processing to throw a DuplicateEntryException.");
      } catch (DuplicateEntryException e) {
        assertEquals("meaning/of/life", e.getPath());
        assertEquals("42", content(e.getSource()));
      }
    }

    @Test
    public void testPolicyThrowUser() throws IOException {
      DuplicateHandler alwaysThrow = DuplicateHandler.always(DuplicateAction.THROW);
      JarBuilder jarBuilder =
          jarBuilder()
              .add(content("1/137"), "meaning/of/life")
              .add(content("!"), "meaning/of/life");

      try {
        jarBuilder.write(true /* compress */, alwaysThrow);
        fail("Expected jar processing to throw a DuplicateEntryException.");
      } catch (DuplicateEntryException e) {
        assertEquals("meaning/of/life", e.getPath());
        assertEquals("!", content(e.getSource()));
      }
    }
  }

  public static class ListenerTest extends WriteTestBase {
    private static final Function<Entry, String> GET_NAME = new Function<Entry, String>() {
      @Override public String apply(Entry entry) {
        return entry.getName();
      }
    };

    @Test
    public void testOnSkip() throws IOException {
      Listener listener = createMock(Listener.class);
      Capture<Iterable<? extends Entry>> skipped = newCapture();
      listener.onSkip(eq(Optional.<Entry>absent()), capture(skipped));
      replay(listener);

      jarBuilder(newFile(), listener)
          .add(content("skipped write"), "skipped/write")
          .write(
              false /* compress */,
              DuplicateHandler.always(DuplicateAction.THROW),
              Pattern.compile("skipped/"));

      assertEquals("skipped/write", Iterables.getOnlyElement(skipped.getValue()).getJarPath());
    }

    @Test
    public void testOnWrite() throws IOException {
      Listener listener = createMock(Listener.class);
      Capture<Entry> written = newCapture();

      listener.onWrite(capture(written));
      replay(listener);

      jarBuilder(newFile(), listener)
          .add(content("simple write"), "simple/write")
          .write();

      assertEquals("simple/write", written.getValue().getJarPath());
    }

    @Test
    public void testOnDuplicateSkip() throws IOException {
      Listener listener = createMock(Listener.class);
      Capture<Optional<Entry>> retained = newCapture();
      Capture<Iterable<? extends Entry>> skipped = newCapture();
      listener.onSkip(capture(retained), capture(skipped));
      replay(listener);

      File one = newFile("one");
      File two = newFile("two");
      File three = newFile("three");

      jarBuilder(newFile(), listener)
          .addFile(one, "skipped/write")
          .addFile(two, "skipped/write")
          .addFile(three, "skipped/write")
          .write(false /* compress */, DuplicateHandler.always(DuplicateAction.SKIP));

      assertEquals("one", retained.getValue().get().getName());
      assertEquals("skipped/write", retained.getValue().get().getJarPath());
      assertEquals(ImmutableList.of("two", "three"),
          FluentIterable.from(skipped.getValue()).transform(GET_NAME).toList());
    }

    @Test
    public void testOnDuplicateConcat() throws IOException {
      Listener listener = createMock(Listener.class);
      Capture<Iterable<? extends Entry>> concatenated = newCapture();
      listener.onConcat(eq("concatenated/write"), capture(concatenated));
      replay(listener);

      File one = newFile("one");
      File two = newFile("two");
      File three = newFile("three");

      jarBuilder(newFile(), listener)
          .addFile(one, "concatenated/write")
          .addFile(two, "concatenated/write")
          .addFile(three, "concatenated/write")
          .write(false /* compress */, DuplicateHandler.always(DuplicateAction.CONCAT));

      assertEquals(ImmutableList.of("one", "two", "three"),
          FluentIterable.from(concatenated.getValue()).transform(GET_NAME).toList());
    }


    @Test
    public void testOnDuplicateConcatText() throws IOException {
      Listener listener = createMock(Listener.class);
      Capture<Iterable<? extends Entry>> concatenated = newCapture();
      listener.onConcat(eq("concatenated/write"), capture(concatenated));
      replay(listener);

      File one = newFile("one");
      File two = newFile("two");
      File three = newFile("three");

      jarBuilder(newFile(), listener)
          .addFile(one, "concatenated/write")
          .addFile(two, "concatenated/write")
          .addFile(three, "concatenated/write")
          .write(false /* compress */, DuplicateHandler.always(DuplicateAction.CONCAT_TEXT));

      assertEquals(ImmutableList.of("one", "two", "three"),
          FluentIterable.from(concatenated.getValue()).transform(GET_NAME).toList());
    }

    @Test
    public void testOnDuplicateReplace() throws IOException {
      Listener listener = createMock(Listener.class);
      Capture<Iterable<? extends Entry>> originals = newCapture();
      Capture<Entry> replacement = newCapture();
      listener.onReplace(capture(originals), capture(replacement));
      replay(listener);

      File one = newFile("one");
      File two = newFile("two");
      File three = newFile("three");

      jarBuilder(newFile(), listener)
          .addFile(one, "replaced/write")
          .addFile(two, "replaced/write")
          .addFile(three, "replaced/write")
          .write(false /* compress */, DuplicateHandler.always(DuplicateAction.REPLACE));

      assertEquals(ImmutableList.of("one", "two"),
          FluentIterable.from(originals.getValue()).transform(GET_NAME).toList());
      assertEquals("three", replacement.getValue().getName());
      assertEquals("replaced/write", replacement.getValue().getJarPath());
    }
  }

  public static class RelpathTest {

    private static void assertRelpath(File fullPath, File relativeTo, String... entries) {
      assertEquals(ImmutableList.copyOf(entries),
          ImmutableList.copyOf(JarBuilder.relpathComponents(fullPath, relativeTo)));
    }

    @Test
    public void testRelpathExact() {
      assertRelpath(new File("/a/b/c"), new File("/a/b/c"));

      assertRelpath(new File("a/b/c"), new File("a/b/c"));
    }

    @Test
    public void testRelpathNested() {
      assertRelpath(new File("/a/b/c"), new File("/a"), "b", "c");
      assertRelpath(new File("/a/b/c"), new File("/a/b"), "c");

      assertRelpath(new File("a/b/c"), new File("a"), "b", "c");
      assertRelpath(new File("a/b/c"), new File("a/b"), "c");
    }

    @Test
    public void testRelpathSibling() {
      assertRelpath(new File("/a/b/c"), new File("/a/b/d"), "..", "c");
      assertRelpath(new File("/a/b/c"), new File("/a/d/e"), "..", "..", "b", "c");
      assertRelpath(new File("/a/b/c"), new File("/d/e/f"), "..", "..", "..", "a", "b", "c");

      assertRelpath(new File("a/b/c"), new File("a/b/d"), "..", "c");
      assertRelpath(new File("a/b/c"), new File("a/d/e"), "..", "..", "b", "c");
      assertRelpath(new File("a/b/c"), new File("d/e/f"), "..", "..", "..", "a", "b", "c");
    }
  }

  public static class PathJoinTest {

    private static void assertJoinPath(String expected, String... components) {
      assertEquals(expected, JarBuilder.joinJarPath(ImmutableList.copyOf(components)));
    }

    @Test
    public void testJoin() {
      assertJoinPath("a/b/c", "a", "b", "c");
      assertJoinPath("a/b/c", "a/", "b", "c");
      assertJoinPath("a/b/c", "a", "b/", "c");
      assertJoinPath("a/b/c/", "a", "b", "c/");
      assertJoinPath("a/b/c", "a", "b//", "c");
      assertJoinPath("a/b/c/", "a", "b", "c/");
      assertJoinPath("/a/b/c/", "/a", "b", "c/");
      assertJoinPath("/a/b/c/", "//a", "b", "c/");
    }
  }
}
