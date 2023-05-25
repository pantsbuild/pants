// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.jar;

import com.google.common.annotations.VisibleForTesting;
import com.google.common.base.Charsets;
import com.google.common.base.Function;
import com.google.common.base.Joiner;
import com.google.common.base.MoreObjects;
import com.google.common.base.Optional;
import com.google.common.base.Preconditions;
import com.google.common.base.Predicate;
import com.google.common.base.Predicates;
import com.google.common.base.Splitter;
import com.google.common.collect.FluentIterable;
import com.google.common.collect.HashMultimap;
import com.google.common.collect.ImmutableList;
import com.google.common.collect.Iterables;
import com.google.common.collect.LinkedListMultimap;
import com.google.common.collect.Lists;
import com.google.common.collect.Multimap;
import com.google.common.collect.Sets;
import com.google.common.io.ByteProcessor;
import com.google.common.io.ByteSource;
import com.google.common.io.Closer;
import com.google.common.io.Files;
import java.io.BufferedOutputStream;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.Closeable;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Collection;
import java.util.Collections;
import java.util.Enumeration;
import java.util.Iterator;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.jar.Attributes.Name;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.jar.JarOutputStream;
import java.util.jar.Manifest;
import java.util.regex.Pattern;
import java.util.zip.CRC32;
import java.util.zip.ZipException;
import javax.annotation.Nullable;

/** A utility than can create or update jar archives with special handling of duplicate entries. */
public class JarBuilder implements Closeable {

  /** Indicates a problem encountered when building up a jar's contents for writing out. */
  public static class JarBuilderException extends IOException {
    public JarBuilderException(String message) {
      super(message);
    }

    public JarBuilderException(String message, Throwable cause) {
      super(message, cause);
    }
  }

  /** Indicates a problem writing out a jar. */
  public static class JarCreationException extends JarBuilderException {
    public JarCreationException(String message) {
      super(message);
    }
  }

  /**
   * Indicates a problem indexing a pre-existing jar that will be added or updated to the target
   * jar.
   */
  public static class IndexingException extends JarBuilderException {
    public IndexingException(File jarPath, Throwable t) {
      super("Problem indexing jar at " + jarPath + ": " + t.getMessage(), t);
    }
  }

  /** Indicates a duplicate jar entry is being rejected. */
  public static class DuplicateEntryException extends RuntimeException {
    private final ReadableEntry entry;

    DuplicateEntryException(ReadableEntry entry) {
      super("Detected a duplicate entry for " + entry.getJarPath());
      this.entry = entry;
    }

    /** @return the duplicate path. */
    public String getPath() {
      return entry.getJarPath();
    }

    /** @return the contents of duplicate entry */
    public ByteSource getSource() {
      return entry.contents;
    }
  }

  /** Identifies an action to take when duplicate jar entries are encountered. */
  public enum DuplicateAction {

    /** This action skips the duplicate entry keeping the original entry. */
    SKIP,

    /** This action replaces the original entry with the duplicate entry. */
    REPLACE,

    /**
     * This action appends the content of the duplicate entry to the original entry. Treats the
     * resources are binary files.
     */
    CONCAT,

    /**
     * Same as CONCAT, but treats these entries as newline delimited text files. Appends a newline
     * to the end of the file if needed in order to separate file entries.
     */
    CONCAT_TEXT,

    /** This action throws a {@link DuplicateEntryException}. */
    THROW
  }

  /** Encapsulates a policy for treatment of duplicate jar entries. */
  public static class DuplicatePolicy implements Predicate<CharSequence> {

    /**
     * Creates a policy that applies to entries based on a path match.
     *
     * @param regex A regular expression to match entry paths against.
     * @param action The action to apply to duplicate entries with path matching {@code regex}.
     * @return The path matching policy.
     */
    public static DuplicatePolicy pathMatches(String regex, DuplicateAction action) {
      return new DuplicatePolicy(Predicates.containsPattern(regex), action);
    }

    private final Predicate<CharSequence> selector;
    private final DuplicateAction action;

    /**
     * Creates a policy that will be applied to duplicate entries matching the given {@code
     * selector}.
     *
     * @param selector A predicate that selects entries this policy has jurisdiction over.
     * @param action The action to apply to entries selected by this policy.
     */
    public DuplicatePolicy(Predicate<CharSequence> selector, DuplicateAction action) {
      this.selector = Preconditions.checkNotNull(selector);
      this.action = Preconditions.checkNotNull(action);
    }

    /**
     * @return The action that should be applied when a duplicate entry falls under this policy's
     *     jurisdiction.
     */
    public DuplicateAction getAction() {
      return action;
    }

    @Override
    public boolean apply(CharSequence jarPath) {
      return selector.apply(jarPath);
    }

    @Override
    public String toString() {
      return MoreObjects.toStringHelper(this)
          .add("action", action)
          .add("selector", selector)
          .toString();
    }
  }

  /** Handles duplicate jar entries by selecting an appropriate action based on the entry path. */
  public static class DuplicateHandler {

    /**
     * Creates a handler that always applies the given {@code action}.
     *
     * @param action The action to perform on all duplicate entries encountered.
     * @return a handler
     */
    public static DuplicateHandler always(DuplicateAction action) {
      Preconditions.checkNotNull(action);
      return new DuplicateHandler(
          action,
          ImmutableList.of(new DuplicatePolicy(Predicates.<CharSequence>alwaysTrue(), action)));
    }

    /**
     * Creates a handler that merges well-known mergable resources and otherwise skips duplicates.
     *
     * <p>Merged resources include META-INF/services/ files.
     *
     * @return a handler
     */
    public static DuplicateHandler skipDuplicatesConcatWellKnownMetadata() {
      DuplicatePolicy concatServices =
          DuplicatePolicy.pathMatches("^META-INF/services/", DuplicateAction.CONCAT_TEXT);
      ImmutableList<DuplicatePolicy> policies = ImmutableList.of(concatServices);
      return new DuplicateHandler(DuplicateAction.SKIP, policies);
    }

    private final DuplicateAction defaultAction;
    private final Iterable<DuplicatePolicy> policies;

    /**
     * A convenience constructor equivalent to calling: {@code DuplicateHandler(defaultAction,
     * Arrays.asList(policies))}
     *
     * @param defaultAction The default action to apply when no policy matches.
     * @param policies The policies to apply in preference order.
     */
    public DuplicateHandler(DuplicateAction defaultAction, DuplicatePolicy... policies) {
      this(defaultAction, ImmutableList.copyOf(policies));
    }

    /**
     * Creates a handler that applies the 1st matching policy when a duplicate entry is encountered,
     * falling back to the given {@code defaultAction} if no policy applies.
     *
     * @param defaultAction The default action to apply when no policy matches.
     * @param policies The policies to apply in preference order.
     */
    public DuplicateHandler(DuplicateAction defaultAction, Iterable<DuplicatePolicy> policies) {
      this.defaultAction = Preconditions.checkNotNull(defaultAction);
      this.policies = ImmutableList.copyOf(policies);
    }

    @VisibleForTesting
    DuplicateAction actionFor(String jarPath) {
      for (DuplicatePolicy policy : policies) {
        if (policy.apply(jarPath)) {
          return policy.getAction();
        }
      }
      return defaultAction;
    }
  }

  /** Identifies a source for jar entries. */
  public interface Source {

    /** @return a name for this source. */
    String name();

    /**
     * Identifies a member of this source.
     *
     * @param name The name of the source
     * @return identity
     */
    String identify(String name);
  }

  private abstract static class FileSource implements Source {
    protected final File source;

    protected FileSource(File source) {
      this.source = source;
    }

    @Override
    public String name() {
      return source.getPath();
    }
  }

  private abstract static class JarSource extends FileSource {
    protected JarSource(File source) {
      super(source);
    }
  }

  /**
   * Joins the path components together with the JAR_PATH_JOINER char.
   *
   * <p>Sanitation is performed to ensure that no consecutive JAR_PATH_JOINER chars appear in the
   * output string.
   *
   * @param path List of jar path components.
   * @return The path string.
   */
  @VisibleForTesting
  static String joinJarPath(Iterable<String> path) {
    return JAR_PATH_JOINER.join(path).replaceAll("/{2,}", "/");
  }

  private static Source jarSource(File jar) {
    return new JarSource(jar) {
      @Override
      public String identify(String name) {
        return String.format("%s!%s", source.getPath(), name);
      }

      @Override
      public String toString() {
        return String.format("JarSource{jar=%s}", source.getPath());
      }
    };
  }

  private static Source fileSource(final File file) {
    return new FileSource(new File("/")) {
      @Override
      public String identify(String name) {
        if (!file.getPath().equals(name)) {
          throw new IllegalArgumentException(
              "Cannot identify any entry name save for " + file.getPath());
        }
        return file.getPath();
      }

      @Override
      public String toString() {
        return String.format("FileSource{file=%s}", file.getPath());
      }
    };
  }

  private static Source directorySource(File directory) {
    return new FileSource(directory) {
      @Override
      public String identify(String name) {
        return new File(source, name).getPath();
      }

      @Override
      public String toString() {
        return String.format("FileSource{directory=%s}", source.getPath());
      }
    };
  }

  private static Source memorySource() {
    return new Source() {
      @Override
      public String name() {
        return "<memory>";
      }

      @Override
      public String identify(String name) {
        return "<memory>!" + name;
      }

      @Override
      public String toString() {
        return String.format("MemorySource{@%s}", Integer.toHexString(hashCode()));
      }
    };
  }

  /** Input stream that always ensures that a non-empty stream ends with a newline. */
  // TODO: implement read(byte[], int, int) for faster multibyte reads
  @SuppressWarnings("InputStreamSlowMultibyteRead")
  private static class NewlineAppendingInputStream extends InputStream {
    private InputStream underlyingStream;
    private int lastByteRead = -1;
    private boolean atEOS = false;

    public NewlineAppendingInputStream(InputStream stream) {
      this.underlyingStream = stream;
    }

    @Override
    public int read() throws IOException {
      if (atEOS) {
        return -1;
      }

      int nextByte = this.underlyingStream.read();
      if (nextByte == -1) {

        atEOS = true;
        if (lastByteRead == -1 || lastByteRead == '\n') {
          return -1;
        }
        return '\n';
      }
      lastByteRead = nextByte;
      return nextByte;
    }
  }

  private static final class NamedTextByteSource extends NamedByteSource {
    private NamedTextByteSource(NamedByteSource source) {
      super(source.source, source.name, source.inputSupplier);
    }

    @Override
    public InputStream openStream() throws IOException {
      return new NewlineAppendingInputStream(inputSupplier.openStream());
    }
  }

  private static class NamedByteSource extends ByteSource {
    static NamedByteSource create(Source source, String name, ByteSource inputSupplier) {
      return new NamedByteSource(source, name, inputSupplier);
    }

    protected final Source source;
    protected final String name;
    protected final ByteSource inputSupplier;

    private NamedByteSource(Source source, String name, ByteSource inputSupplier) {
      this.source = source;
      this.name = name;
      this.inputSupplier = inputSupplier;
    }

    @Override
    public InputStream openStream() throws IOException {
      return inputSupplier.openStream();
    }
  }

  /** Represents an entry to be added to a jar. */
  public interface Entry {
    /** @return the source that contains the entry. */
    Source getSource();

    /** @return the name of the entry within its source. */
    String getName();

    /** @return the path this entry will be added into the jar at. */
    String getJarPath();
  }

  private static class ReadableTextEntry extends ReadableEntry {
    static final Function<ReadableEntry, NamedByteSource> GET_CONTENTS =
        new Function<ReadableEntry, NamedByteSource>() {
          @Override
          public NamedByteSource apply(ReadableEntry item) {
            return new NamedTextByteSource(item.contents);
          }
        };

    ReadableTextEntry(NamedByteSource contents, String path) {
      super(contents, path);
    }
  }

  private static class ReadableEntry implements Entry {
    static final Function<ReadableEntry, NamedByteSource> GET_CONTENTS =
        new Function<ReadableEntry, NamedByteSource>() {
          @Override
          public NamedByteSource apply(ReadableEntry item) {
            return item.contents;
          }
        };

    private final NamedByteSource contents;
    private final String path;

    ReadableEntry(NamedByteSource contents, String path) {
      this.contents = contents;
      this.path = path;
    }

    @Override
    public Source getSource() {
      return contents.source;
    }

    @Override
    public String getName() {
      return contents.name;
    }

    @Override
    public String getJarPath() {
      return path;
    }
  }

  private static class ReadableJarEntry extends ReadableEntry {
    private final JarEntry jarEntry;

    public ReadableJarEntry(NamedByteSource contents, JarEntry jarEntry) {
      super(contents, jarEntry.getName());
      this.jarEntry = jarEntry;
    }

    public JarEntry getJarEntry() {
      return jarEntry;
    }
  }

  /** An interface for those interested in the progress of writing the target jar. */
  public interface Listener {
    /** A listener that ignores all events. */
    Listener NOOP =
        new Listener() {
          @Override
          public void onSkip(
              Optional<? extends Entry> original, Iterable<? extends Entry> skipped) {
            // noop
          }

          @Override
          public void onReplace(Iterable<? extends Entry> originals, Entry replacement) {
            // noop
          }

          @Override
          public void onConcat(String name, Iterable<? extends Entry> entries) {
            // noop
          }

          @Override
          public void onWrite(Entry entry) {
            // noop
          }
        };

    /**
     * Called to notify the listener that entries are being skipped.
     *
     * <p>If original is present this indicates it it being retained in preference to the skipped
     * entries.
     *
     * @param original The original entry being retained.
     * @param skipped The new entries being skipped.
     */
    void onSkip(Optional<? extends Entry> original, Iterable<? extends Entry> skipped);

    /**
     * Called to notify the listener that original entries are being replaced by a subsequently
     * added entry.
     *
     * @param originals The original entry candidates that will be replaced.
     * @param replacement The entry that overwrites the originals.
     */
    void onReplace(Iterable<? extends Entry> originals, Entry replacement);

    /**
     * Called to notify the listener an original entry is being concatenated with one or more
     * subsequently added entries.
     *
     * @param name The name of the entry in question.
     * @param entries The entries that will be concatenated with the original entry.
     */
    void onConcat(String name, Iterable<? extends Entry> entries);

    /**
     * Called to notify the listener of a newly written non-duplicate entry.
     *
     * @param entry The entry to be added to the target jar.
     */
    void onWrite(Entry entry);
  }

  private static ByteSource manifestSupplier(final Manifest mf) {
    return new ByteSource() {
      @Override
      public InputStream openStream() throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        mf.write(out);
        return new ByteArrayInputStream(out.toByteArray());
      }
    };
  }

  static Manifest ensureDefaultManifestEntries(Manifest manifest) {
    if (!manifest.getMainAttributes().containsKey(Name.MANIFEST_VERSION)) {
      manifest.getMainAttributes().put(Name.MANIFEST_VERSION, "1.0");
    }
    Name createdBy = new Name("Created-By");
    if (!manifest.getMainAttributes().containsKey(createdBy)) {
      manifest.getMainAttributes().put(createdBy, JarBuilder.class.getName());
    }
    return manifest;
  }

  private static Manifest createDefaultManifest() {
    return ensureDefaultManifestEntries(new Manifest());
  }

  private static final ByteSource DEFAULT_MANIFEST = manifestSupplier(createDefaultManifest());

  private interface InputSupplier<T> {
    T getInput() throws IOException;
  }

  private static class JarSupplier implements InputSupplier<JarFile>, Closeable {
    private final Closer closer;
    private final InputSupplier<JarFile> supplier;

    JarSupplier(final File file) {
      closer = Closer.create();
      supplier =
          new InputSupplier<JarFile>() {
            @Override
            public JarFile getInput() throws IOException {
              try {
                // Do not verify signed.
                return JarFileUtil.openJarFile(closer, file, false);
              } catch (ZipException zex) {
                // JarFile is not very verbose and doesn't tell the user which file it was
                // so we will create a new Exception instead
                ZipException e = new ZipException("error in opening zip file " + file);
                e.initCause(zex);
                throw e;
              }
            }
          };
    }

    @Override
    public JarFile getInput() throws IOException {
      return supplier.getInput();
    }

    @Override
    public void close() throws IOException {
      closer.close();
    }
  }

  private static final Splitter JAR_PATH_SPLITTER = Splitter.on('/');
  private static final Joiner JAR_PATH_JOINER = Joiner.on('/');

  /*
   * Implementations should add jar entries to the given {@code Multimap} index when executed.
   */
  private interface EntryIndexer {
    void execute(Multimap<String, ReadableEntry> entries) throws JarBuilderException;
  }

  private final File target;
  private final Listener listener;
  private final Closer closer = Closer.create();
  private final List<EntryIndexer> additions = Lists.newLinkedList();

  @Nullable private ByteSource manifest;

  /**
   * Creates a JarBuilder that will write scheduled jar additions to {@code target} upon {@link
   * #write}.
   *
   * <p>If the {@code target} exists an attempt will be made to over-write it and if it does not
   * exist a then a new jar will be created at its path.
   *
   * @param target The target jar file to write.
   */
  public JarBuilder(File target) {
    this(target, Listener.NOOP);
  }

  /**
   * Creates a JarBuilder that will write scheduled jar additions to {@code target} upon {@link
   * #write}.
   *
   * <p>If the {@code target} does not exist a new jar will be created at its path.
   *
   * @param target The target jar file to write.
   * @param listener A progress listener
   */
  public JarBuilder(File target, Listener listener) {
    this.target = Preconditions.checkNotNull(target);
    this.listener = Preconditions.checkNotNull(listener);
  }

  @Override
  public void close() throws IOException {
    closer.close();
  }

  /**
   * Schedules addition of the given {@code contents} to the entry at {@code jarPath}. In addition,
   * individual parent directory entries will be created when this builder is {@link #write written}
   * in he spirit of {@code mkdir -p}.
   *
   * @param contents The contents of the entry to add.
   * @param jarPath The path of the entry to add.
   * @return This builder for chaining.
   */
  public JarBuilder add(final ByteSource contents, final String jarPath) {
    Preconditions.checkNotNull(contents);
    Preconditions.checkNotNull(jarPath);

    additions.add(
        new EntryIndexer() {
          @Override
          public void execute(Multimap<String, ReadableEntry> entries) {
            add(entries, NamedByteSource.create(memorySource(), jarPath, contents), jarPath);
          }
        });
    return this;
  }

  private static boolean isEmpty(@Nullable String value) {
    return value == null || value.trim().isEmpty();
  }

  /**
   * Schedules recursive addition of all files contained within {@code directory} to the resulting
   * jar. The path of each file relative to {@code directory} will be used for the corresponding jar
   * entry path. If a {@code jarPath} is present then all subtree entries will be prefixed with it.
   *
   * @param directory An existing directory to add to the jar.
   * @param jarPath An optional base path to graft the {@code directory} onto.
   * @return This builder for chaining.
   */
  public JarBuilder addDirectory(final File directory, final Optional<String> jarPath) {
    Preconditions.checkArgument(
        directory.isDirectory(), "Expected a directory, given a file: %s", directory);
    Preconditions.checkArgument(!jarPath.isPresent() || !isEmpty(jarPath.get()));

    additions.add(
        new EntryIndexer() {
          @Override
          public void execute(Multimap<String, ReadableEntry> entries) throws JarBuilderException {

            Source directorySource = directorySource(directory);
            Iterable<String> jarBasePath =
                jarPath.isPresent()
                    ? JAR_PATH_SPLITTER.split(jarPath.get())
                    : ImmutableList.<String>of();

            Iterable<File> files =
                Files.fileTreeTraverser().preOrderTraversal(directory).filter(Files.isFile());

            for (File child : files) {
              Iterable<String> relpathComponents = relpathComponents(child, directory);
              Iterable<String> path = Iterables.concat(jarBasePath, relpathComponents);
              String entryPath = joinJarPath(relpathComponents);
              String entryJarPath = joinJarPath(path);
              if (!JarFile.MANIFEST_NAME.equals(entryJarPath)) {
                NamedByteSource contents =
                    NamedByteSource.create(directorySource, entryPath, Files.asByteSource(child));
                add(entries, contents, entryJarPath);
              }
            }
          }
        });
    return this;
  }

  /**
   * Schedules addition of the given {@code file}'s contents to the entry at {@code jarPath}. In
   * addition, individual parent directory entries will be created when this builder is {@link
   * #write written} in the spirit of {@code mkdir -p}.
   *
   * @param file An existing file to add to the jar.
   * @param jarPath The path of the entry to add.
   * @return This builder for chaining.
   */
  public JarBuilder addFile(final File file, final String jarPath) {
    Preconditions.checkArgument(
        !file.isDirectory(), "Expected a file, given a directory: %s", file);
    Preconditions.checkArgument(!isEmpty(jarPath));

    additions.add(
        new EntryIndexer() {
          @Override
          public void execute(Multimap<String, ReadableEntry> entries) throws JarBuilderException {

            if (JarFile.MANIFEST_NAME.equals(jarPath)) {
              throw new JarBuilderException(
                  "A custom manifest entry should be added via the useCustomManifest methods");
            }
            NamedByteSource contents =
                NamedByteSource.create(fileSource(file), file.getName(), Files.asByteSource(file));
            add(entries, contents, jarPath);
          }
        });
    return this;
  }

  /**
   * Schedules addition of the given jar's contents to the file at {@code jarPath}. Even if the jar
   * does not contain individual parent directory entries, they will be added for each entry added.
   *
   * @param file The path of the jar to add.
   * @return This builder for chaining.
   */
  public JarBuilder addJar(final File file) {
    Preconditions.checkNotNull(file);

    additions.add(
        new EntryIndexer() {
          @Override
          public void execute(final Multimap<String, ReadableEntry> entries)
              throws IndexingException {

            final InputSupplier<JarFile> jarSupplier = closer.register(new JarSupplier(file));
            final Source jarSource = jarSource(file);
            try {
              enumerateJarEntries(
                  file,
                  new JarEntryVisitor() {
                    @Override
                    public void visit(JarEntry entry) throws IOException {
                      if (!entry.isDirectory() && !JarFile.MANIFEST_NAME.equals(entry.getName())) {
                        NamedByteSource contents =
                            NamedByteSource.create(
                                jarSource, entry.getName(), entrySupplier(jarSupplier, entry));
                        add(entries, contents, entry);
                      }
                    }
                  });
            } catch (IOException e) {
              throw new IndexingException(file, e);
            }
          }
        });
    return this;
  }

  private static void add(
      Multimap<String, ReadableEntry> entries, NamedByteSource contents, String jarPath) {

    entries.put(jarPath, new ReadableEntry(contents, jarPath));
  }

  private static void add(
      Multimap<String, ReadableEntry> entries, NamedByteSource contents, JarEntry jarEntry) {

    entries.put(jarEntry.getName(), new ReadableJarEntry(contents, jarEntry));
  }

  /**
   * Registers the given Manifest to be used in the jar written out by {@link #write}.
   *
   * @param customManifest The manifest to use for the built jar.
   * @return This builder for chaining.
   */
  public JarBuilder useCustomManifest(final Manifest customManifest) {
    Preconditions.checkNotNull(customManifest);

    manifest = manifestSupplier(customManifest);
    return this;
  }

  /**
   * Registers the given Manifest to be used in the jar written out by {@link #write}.
   *
   * @param customManifest The manifest to use for the built jar.
   * @return This builder for chaining.
   */
  public JarBuilder useCustomManifest(File customManifest) {
    Preconditions.checkNotNull(customManifest);

    NamedByteSource contents =
        NamedByteSource.create(
            fileSource(customManifest),
            customManifest.getPath(),
            Files.asByteSource(customManifest));
    return useCustomManifest(contents);
  }

  /**
   * Registers the given Manifest to be used in the jar written out by {@link #write}.
   *
   * @param customManifest The manifest to use for the built jar.
   * @return This builder for chaining.
   */
  public JarBuilder useCustomManifest(CharSequence customManifest) {
    Preconditions.checkNotNull(customManifest);

    return useCustomManifest(
        NamedByteSource.create(
            memorySource(),
            JarFile.MANIFEST_NAME,
            ByteSource.wrap(customManifest.toString().getBytes(Charsets.UTF_8))));
  }

  /**
   * Registers the given Manifest to be used in the jar written out by {@link #write}.
   *
   * @param customManifest The manifest to use for the built jar.
   * @return This builder for chaining.
   */
  public JarBuilder useCustomManifest(final NamedByteSource customManifest) {
    Preconditions.checkNotNull(customManifest);
    return useCustomManifest(
        new InputSupplier<Manifest>() {
          @Override
          public Manifest getInput() throws IOException {
            Manifest mf = new Manifest();
            try {
              mf.read(customManifest.openStream());
              return mf;
            } catch (IOException e) {
              throw new JarCreationException(
                  "Invalid manifest from " + customManifest.source.identify(customManifest.name));
            }
          }
        });
  }

  private JarBuilder useCustomManifest(final InputSupplier<Manifest> manifestSource) {
    manifest =
        new ByteSource() {
          @Override
          public InputStream openStream() throws IOException {
            return manifestSupplier(manifestSource.getInput()).openStream();
          }
        };
    return this;
  }

  /**
   * Creates a jar at the configured target path applying the scheduled additions and skipping any
   * duplicate entries found. Entries will not be compressed.
   *
   * @return The jar file that was written.
   * @throws IOException if there was a problem writing the jar file.
   */
  public File write() throws IOException {
    return write(false, DuplicateHandler.always(DuplicateAction.SKIP));
  }

  /**
   * Creates a jar at the configured target path applying the scheduled additions and skipping any
   * duplicate entries found.
   *
   * @param compress Pass {@code true} to compress all jar entries; otherwise, they will just be
   *     stored.
   * @return The jar file that was written.
   * @throws IOException if there was a problem writing the jar file.
   */
  public File write(boolean compress) throws IOException {
    return write(compress, DuplicateHandler.always(DuplicateAction.SKIP));
  }

  /**
   * Creates a jar at the configured target path applying the scheduled additions per the given
   * {@code duplicateHandler}.
   *
   * @param compress Pass {@code true} to compress all jar entries; otherwise, they will just be
   *     stored.
   * @param duplicateHandler A handler for dealing with duplicate entries.
   * @param skipPatterns An optional list of patterns that match entry paths that should be
   *     excluded.
   * @return The jar file that was written.
   * @throws IOException if there was a problem writing the jar file.
   * @throws DuplicateEntryException if the policy in effect for an entry is {@link
   *     DuplicateAction#THROW} and that entry is a duplicate.
   */
  public File write(boolean compress, DuplicateHandler duplicateHandler, Pattern... skipPatterns)
      throws IOException {

    return write(compress, duplicateHandler, ImmutableList.copyOf(skipPatterns));
  }

  private static final Function<Pattern, Predicate<CharSequence>> AS_PATH_SELECTOR =
      new Function<Pattern, Predicate<CharSequence>>() {
        @Override
        public Predicate<CharSequence> apply(Pattern item) {
          return Predicates.contains(item);
        }
      };

  /**
   * Creates a jar at the configured target path applying the scheduled additions per the given
   * {@code duplicateHandler}.
   *
   * @param compress Pass {@code true} to compress all jar entries; otherwise, they will just be
   *     stored.
   * @param duplicateHandler A handler for dealing with duplicate entries.
   * @param skipPatterns An optional sequence of patterns that match entry paths that should be
   *     excluded.
   * @return The jar file that was written.
   * @throws IOException if there was a problem writing the jar file.
   * @throws DuplicateEntryException if the policy in effect for an entry is {@link
   *     DuplicateAction#THROW} and that entry is a duplicate.
   */
  public File write(
      final boolean compress, DuplicateHandler duplicateHandler, Iterable<Pattern> skipPatterns)
      throws DuplicateEntryException, IOException {

    Preconditions.checkNotNull(duplicateHandler);
    Predicate<CharSequence> skipPath =
        Predicates.or(Iterables.transform(ImmutableList.copyOf(skipPatterns), AS_PATH_SELECTOR));

    final Iterable<ReadableEntry> entries = getEntries(skipPath, duplicateHandler);

    File tmp = File.createTempFile(target.getName(), ".tmp", target.getParentFile());
    try {
      try {
        JarWriter writer = jarWriter(tmp, compress);
        writer.write(JarFile.MANIFEST_NAME, manifest == null ? DEFAULT_MANIFEST : manifest);
        List<ReadableJarEntry> jarEntries = Lists.newArrayList();
        for (ReadableEntry entry : entries) {
          if (entry instanceof ReadableJarEntry) {
            jarEntries.add((ReadableJarEntry) entry);
          } else {
            writer.write(entry.getJarPath(), entry.contents);
          }
        }
        copyJarFiles(writer, jarEntries);

        // Close all open files, the moveFile below might need to copy instead of just rename.
        closer.close();

        // Rename the file (or copy if it can't be renamed)
        target.delete();
        Files.move(tmp, target);
      } catch (IOException e) {
        throw closer.rethrow(e);
      } finally {
        closer.close();
      }
    } finally {
      tmp.delete();
    }
    return target;
  }

  /**
   * As an optimization, use {@link JarEntryCopier} to copy one jar file to another without
   * decompressing and recompressing.
   *
   * @param writer target to copy JAR file entries to.
   * @param entries entries that came from a jar file
   */
  private void copyJarFiles(JarWriter writer, Iterable<ReadableJarEntry> entries)
      throws IOException {
    // Walk the entries to bucketize by input jar file names
    Multimap<JarSource, ReadableJarEntry> jarEntries = HashMultimap.create();
    for (ReadableJarEntry entry : entries) {
      Preconditions.checkState(entry.getSource() instanceof JarSource);
      jarEntries.put((JarSource) entry.getSource(), entry);
    }

    // Copy the data from each jar input file to the output
    for (JarSource source : jarEntries.keySet()) {
      Closer jarFileCloser = Closer.create();
      try {
        final InputSupplier<JarFile> jarSupplier =
            jarFileCloser.register(new JarSupplier(new File(source.name())));
        JarFile jarFile = jarSupplier.getInput();
        for (ReadableJarEntry readableJarEntry : jarEntries.get(source)) {
          JarEntry jarEntry = readableJarEntry.getJarEntry();
          String resource = jarEntry.getName();
          writer.copy(resource, jarFile, jarEntry);
        }
      } catch (IOException ex) {
        throw jarFileCloser.rethrow(ex);
      } finally {
        jarFileCloser.close();
      }
    }
  }

  private Iterable<ReadableEntry> getEntries(
      final Predicate<CharSequence> skipPath, final DuplicateHandler duplicateHandler)
      throws JarBuilderException {

    Function<Map.Entry<String, Collection<ReadableEntry>>, Iterable<ReadableEntry>> mergeEntries =
        new Function<Map.Entry<String, Collection<ReadableEntry>>, Iterable<ReadableEntry>>() {
          @Override
          public Iterable<ReadableEntry> apply(Map.Entry<String, Collection<ReadableEntry>> item) {
            String jarPath = item.getKey();
            Collection<ReadableEntry> entries = item.getValue();
            return processEntries(skipPath, duplicateHandler, jarPath, entries).asSet();
          }
        };
    return FluentIterable.from(getAdditions().asMap().entrySet()).transformAndConcat(mergeEntries);
  }

  @SuppressWarnings("UnnecessaryDefaultInEnumSwitch")
  private Optional<ReadableEntry> processEntries(
      Predicate<CharSequence> skipPath,
      DuplicateHandler duplicateHandler,
      String jarPath,
      Collection<ReadableEntry> itemEntries) {

    if (skipPath.apply(jarPath)) {
      listener.onSkip(Optional.<Entry>absent(), itemEntries);
      return Optional.absent();
    }

    if (itemEntries.size() < 2) {
      ReadableEntry entry = Iterables.getOnlyElement(itemEntries);
      listener.onWrite(entry);
      return Optional.of(entry);
    }

    DuplicateAction action = duplicateHandler.actionFor(jarPath);
    switch (action) {
      case SKIP:
        {
          ReadableEntry original = Iterables.get(itemEntries, 0);
          listener.onSkip(Optional.of(original), Iterables.skip(itemEntries, 1));
          return Optional.of(original);
        }

      case REPLACE:
        {
          ReadableEntry replacement = Iterables.getLast(itemEntries);
          listener.onReplace(Iterables.limit(itemEntries, itemEntries.size() - 1), replacement);
          return Optional.of(replacement);
        }
      case CONCAT:
        {
          ByteSource concat =
              ByteSource.concat(Iterables.transform(itemEntries, ReadableEntry.GET_CONTENTS));

          ReadableEntry concatenatedEntry =
              new ReadableEntry(NamedByteSource.create(memorySource(), jarPath, concat), jarPath);

          listener.onConcat(jarPath, itemEntries);
          return Optional.of(concatenatedEntry);
        }

      case CONCAT_TEXT:
        {
          ByteSource concat_text =
              ByteSource.concat(Iterables.transform(itemEntries, ReadableTextEntry.GET_CONTENTS));

          ReadableEntry concatenatedTextEntry =
              new ReadableEntry(
                  NamedByteSource.create(memorySource(), jarPath, concat_text), jarPath);

          listener.onConcat(jarPath, itemEntries);
          return Optional.of(concatenatedTextEntry);
        }

      case THROW:
        throw new DuplicateEntryException(Iterables.get(itemEntries, 1));

      default:
        throw new IllegalArgumentException("Unrecognized DuplicateAction " + action);
    }
  }

  private Multimap<String, ReadableEntry> getAdditions() throws JarBuilderException {
    final Multimap<String, ReadableEntry> entries = LinkedListMultimap.create();
    if (target.exists() && target.length() > 0) {
      final InputSupplier<JarFile> jarSupplier = closer.register(new JarSupplier(target));
      try {
        enumerateJarEntries(
            target,
            new JarEntryVisitor() {
              @Override
              public void visit(JarEntry jarEntry) throws IOException {
                String entryPath = jarEntry.getName();
                ByteSource contents = entrySupplier(jarSupplier, jarEntry);
                if (JarFile.MANIFEST_NAME.equals(entryPath)) {
                  if (manifest == null) {
                    manifest = contents;
                  }
                } else if (!jarEntry.isDirectory()) {
                  entries.put(
                      entryPath,
                      new ReadableJarEntry(
                          NamedByteSource.create(jarSource(target), entryPath, contents),
                          jarEntry));
                }
              }
            });
      } catch (IOException e) {
        throw new IndexingException(target, e);
      }
    }
    for (EntryIndexer addition : additions) {
      addition.execute(entries);
    }
    return entries;
  }

  private interface JarEntryVisitor {
    void visit(JarEntry item) throws IOException;
  }

  private void enumerateJarEntries(File jarFile, JarEntryVisitor visitor) throws IOException {

    Closer jarFileCloser = Closer.create();
    JarFile jar = JarFileUtil.openJarFile(jarFileCloser, jarFile);
    try {
      for (Enumeration<JarEntry> entries = jar.entries(); entries.hasMoreElements(); ) {
        visitor.visit(entries.nextElement());
      }
    } catch (IOException e) {
      throw jarFileCloser.rethrow(e);
    } finally {
      jarFileCloser.close();
    }
  }

  private static final class JarWriter {
    static class EntryFactory {
      private final boolean compress;

      EntryFactory(boolean compress) {
        this.compress = compress;
      }

      JarEntry createEntry(String path, ByteSource contents) throws IOException {

        JarEntry entry = new JarEntry(path);
        entry.setMethod(compress ? JarEntry.DEFLATED : JarEntry.STORED);
        if (!compress) {
          prepareEntry(entry, contents);
        }
        return entry;
      }

      private void prepareEntry(JarEntry entry, ByteSource contents) throws IOException {

        final CRC32 crc32 = new CRC32();
        long size =
            contents.read(
                new ByteProcessor<Long>() {
                  private long size = 0;

                  @Override
                  public boolean processBytes(byte[] buf, int off, int len) throws IOException {
                    size += len;
                    crc32.update(buf, off, len);
                    return true;
                  }

                  @Override
                  public Long getResult() {
                    return size;
                  }
                });
        entry.setSize(size);
        entry.setCompressedSize(size);
        entry.setCrc(crc32.getValue());
      }
    }

    private static final Joiner JAR_PATH_JOINER = Joiner.on('/');

    private final Set<List<String>> directories = Sets.newHashSet();
    private final JarOutputStream out;
    private final EntryFactory entryFactory;

    private JarWriter(JarOutputStream out, boolean compress) {
      this.out = out;
      this.entryFactory = new EntryFactory(compress);
    }

    public void write(String path, ByteSource contents) throws IOException {
      ensureParentDir(path);
      out.putNextEntry(entryFactory.createEntry(path, contents));
      contents.copyTo(out);
    }

    public void copy(String path, JarFile jarIn, JarEntry srcJarEntry) throws IOException {
      ensureParentDir(path);
      JarEntryCopier.copyEntry(out, path, jarIn, srcJarEntry);
    }

    private void ensureParentDir(String path) throws IOException {
      File file = new File(path);
      File parent = file.getParentFile();
      if (parent != null) {
        List<String> components = components(parent);
        List<String> ancestry = Lists.newArrayListWithCapacity(components.size());
        for (String component : components) {
          ancestry.add(component);
          if (!directories.contains(ancestry)) {
            directories.add(ImmutableList.copyOf(ancestry));
            out.putNextEntry(new JarEntry(joinJarPath(ancestry) + "/"));
          }
        }
      }
    }
  }

  private JarWriter jarWriter(File path, boolean compress) throws IOException {
    // The JAR-writing process seems to be I/O bound. To make writes to disk less frequent,
    // BufferedOutputStream is used. This way, compressed data is stored in a buffer before being
    // flushed to disk.
    // For benchmarking, "./pants binary --no-use-nailgun" command was executed on a large project.
    // The machine was 2013 MPB with SSD. The resulting project JAR is about 500 MB.
    // Without BufferedOutputStream, the jar-tool step took on average about 113 seconds.
    // With BufferedOutputStream and 1MB buffer, the jar-tool step took on average about 80 seconds.
    // The performance gain on this particular project on this particular machine is 30%.
    FileOutputStream fout = closer.register(new FileOutputStream(path));
    BufferedOutputStream bout = closer.register(new BufferedOutputStream(fout, 1024 * 1024));
    final JarOutputStream jar = closer.register(new JarOutputStream(bout));
    closer.register(
        new Closeable() {
          @Override
          public void close() throws IOException {
            jar.closeEntry();
          }
        });
    return new JarWriter(jar, compress);
  }

  private static ByteSource entrySupplier(final InputSupplier<JarFile> jar, final JarEntry entry) {
    return new ByteSource() {
      @Override
      public InputStream openStream() throws IOException {
        return jar.getInput().getInputStream(entry);
      }
    };
  }

  @VisibleForTesting
  static Iterable<String> relpathComponents(File fullPath, File relativeTo) {
    List<String> base = components(relativeTo);
    List<String> path = components(fullPath);
    for (Iterator<String> baseIter = base.iterator(), pathIter = path.iterator();
        baseIter.hasNext() && pathIter.hasNext(); ) {
      if (!baseIter.next().equals(pathIter.next())) {
        break;
      } else {
        baseIter.remove();
        pathIter.remove();
      }
    }

    if (!base.isEmpty()) {
      path.addAll(0, Collections.nCopies(base.size(), ".."));
    }
    return path;
  }

  private static List<String> components(File file) {
    LinkedList<String> components = Lists.newLinkedList();
    File path = file;
    do {
      components.addFirst(path.getName());
    } while ((path = path.getParentFile()) != null);
    return components;
  }
}
