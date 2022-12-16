// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.jar;

import com.google.common.base.Function;
import com.google.common.base.Joiner;
import com.google.common.base.MoreObjects;
import com.google.common.base.Optional;
import com.google.common.base.Preconditions;
import com.google.common.base.Splitter;
import com.google.common.base.Strings;
import com.google.common.collect.FluentIterable;
import com.google.common.collect.ImmutableList;
import com.google.common.collect.ImmutableSet;
import com.google.common.collect.Lists;
import com.google.common.io.Closer;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.util.List;
import java.util.jar.Attributes.Name;
import java.util.jar.Manifest;
import java.util.logging.ConsoleHandler;
import java.util.logging.Level;
import java.util.logging.Logger;
import java.util.logging.SimpleFormatter;
import java.util.regex.Pattern;
import java.util.regex.PatternSyntaxException;
import javax.annotation.Nullable;
import org.kohsuke.args4j.Argument;
import org.kohsuke.args4j.CmdLineParser;
import org.kohsuke.args4j.Option;
import org.kohsuke.args4j.OptionDef;
import org.kohsuke.args4j.spi.Setter;
import org.pantsbuild.args4j.ArgfileOptionHandler;
import org.pantsbuild.args4j.CollectionOptionHandler;
import org.pantsbuild.args4j.InvalidCmdLineArgumentException;
import org.pantsbuild.args4j.Parser;
import org.pantsbuild.tools.jar.JarBuilder.DuplicateAction;
import org.pantsbuild.tools.jar.JarBuilder.DuplicateEntryException;
import org.pantsbuild.tools.jar.JarBuilder.DuplicateHandler;
import org.pantsbuild.tools.jar.JarBuilder.DuplicatePolicy;
import org.pantsbuild.tools.jar.JarBuilder.Entry;
import org.pantsbuild.tools.jar.JarBuilder.Listener;
import org.pantsbuild.tools.jar.JarBuilder.Source;

public final class Main {
  public static class Options {
    public static class DuplicatePolicyParser extends CollectionOptionHandler<DuplicatePolicy> {
      private static final Splitter REGEX_ACTION_SPLITTER =
          Splitter.on('=').trimResults().omitEmptyStrings();

      public DuplicatePolicyParser(
          CmdLineParser parser, OptionDef option, Setter<? super DuplicatePolicy> setter) {
        super(
            parser,
            option,
            setter,
            "DUPLICATE_POLICY",
            new ItemParser<DuplicatePolicy>() {
              @Override
              public DuplicatePolicy parse(String item) {
                List<String> components = ImmutableList.copyOf(REGEX_ACTION_SPLITTER.split(item));
                Preconditions.checkArgument(
                    components.size() == 2, "Failed to parse jar path regex/action pair %s", item);

                String regex = components.get(0);
                DuplicateAction action = DuplicateAction.valueOf(components.get(1));
                return DuplicatePolicy.pathMatches(regex, action);
              }
            });
      }
    }

    static class FileSource {
      private static final Splitter JAR_PATH_SPLITTER = Splitter.on('/');

      private final File source;
      @Nullable private final String destination;

      FileSource(File source, @Nullable String destination) {
        if (!source.exists() || !source.canRead()) {
          throw new IllegalArgumentException(
              String.format("The source %s is not a readable path", source));
        }
        if (!source.isDirectory() && destination == null) {
          throw new IllegalArgumentException(
              String.format("The source file %s must have a jar destination specified.", source));
        }
        if (destination != null) {
          Preconditions.checkArgument(
              !Strings.isNullOrEmpty(destination.trim()), "The destination path cannot be blank");
          Preconditions.checkArgument(
              !destination.startsWith("/"),
              "The destination path cannot be absolute, given: %s",
              destination);
          Preconditions.checkArgument(
              !ImmutableSet.copyOf(JAR_PATH_SPLITTER.split(destination)).contains(".."),
              "The destination path cannot be relative, given: %s",
              destination);
        }

        this.source = source;
        this.destination = destination;
      }

      void addTo(JarBuilder jarBuilder) {
        if (source.isDirectory()) {
          jarBuilder.addDirectory(source, Optional.fromNullable(destination));
        } else {
          jarBuilder.addFile(source, destination);
        }
      }

      @Override
      public String toString() {
        return MoreObjects.toStringHelper(this)
            .add("source", source)
            .add("destination", destination)
            .toString();
      }
    }

    public static class FileSourceOptionHandler extends CollectionOptionHandler<FileSource> {
      private static final Splitter DESTINATION_SPLITTER =
          Splitter.on('=').trimResults().omitEmptyStrings();

      public FileSourceOptionHandler(
          CmdLineParser parser, OptionDef option, Setter<? super FileSource> setter) {
        super(
            parser,
            option,
            setter,
            "FILE_SOURCE",
            new ItemParser<FileSource>() {
              @Override
              public FileSource parse(String item) {
                List<String> components = ImmutableList.copyOf(DESTINATION_SPLITTER.split(item));
                Preconditions.checkArgument(
                    1 <= components.size() && components.size() <= 2,
                    "Failed to parse entry %s",
                    item);

                File source = new File(components.get(0));
                @Nullable String destination = components.size() == 2 ? components.get(1) : null;
                return new FileSource(source, destination);
              }
            });
      }
    }

    @Option(
        name = "-h",
        aliases = {"-help"},
        help = true,
        usage = "Display this help screen.")
    private boolean help;

    @Option(
        name = "-main",
        usage =
            "The name of the fully qualified main class. If a -manifest is specified its contents"
                + " will be used but this -main will override any entry already present.")
    private String mainClass;

    public static class ClassPathOptionHandler extends ArgfileOptionHandler<String> {
      public ClassPathOptionHandler(
          CmdLineParser parser, OptionDef option, Setter<? super String> setter) {
        super(
            new CollectionOptionHandler<String>(
                parser,
                option,
                setter,
                "CLASS_PATH_ENTRY",
                CollectionOptionHandler.ItemParser.IDENTITY));
      }
    }

    @Option(
        name = "-classpath",
        usage =
            "A list of comma-separated classpath entries. "
                + "If a -manifest is specified its contents will be used but this -classpath will "
                + "override any entry already present.",
        handler = ClassPathOptionHandler.class)
    private List<String> classPath = null;

    private File manifest;

    @Option(
        name = "-manifest",
        usage =
            "A path to a manifest file to use. If -main or -classpath is specified those "
                + "values will overwrite the corresponding entry in this manifest.")
    void setManifest(File manifest) {
      if (manifest == null) {
        throw new InvalidCmdLineArgumentException("-manifest", manifest, "Cannot be null.");
      }
      if (!manifest.exists()) {
        throw new InvalidCmdLineArgumentException("-manifest", manifest, "Must exist.");
      }
      if (!manifest.isFile()) {
        throw new InvalidCmdLineArgumentException("-manifest", manifest, "Must be a file.");
      }
      if (!manifest.canRead()) {
        throw new InvalidCmdLineArgumentException("-manifest", manifest, "Must be readable.");
      }
      this.manifest = manifest;
    }

    @Option(name = "-update", usage = "Update the jar if it already exists, otherwise create it.")
    private boolean update;

    @Option(name = "-compress", usage = "Compress jar entries.")
    private boolean compress;

    public static class FilesOptionHandler extends ArgfileOptionHandler<FileSource> {
      public FilesOptionHandler(
          CmdLineParser parser, OptionDef option, Setter<? super FileSource> setter) {
        super(new FileSourceOptionHandler(parser, option, setter));
      }
    }

    @Option(
        name = "-files",
        usage =
            "A mapping from filesystem paths to jar paths. The mapping is specified in the form [fs"
                + " path1](=[jar path1]),[fs path2](=[jar path2]). For example:"
                + " /etc/hosts=hosts,/var/log=logs would create a jar with a hosts file entry and"
                + " the contents of the /var/log tree added as individual entries under the logs/"
                + " directory in the jar. For directories, the mapping can be skipped in which case"
                + " the directory tree is added as-is to the resulting jar.",
        handler = FilesOptionHandler.class)
    private List<FileSource> files = Lists.newArrayList();

    public static class JarsOptionHandler extends ArgfileOptionHandler<File> {
      public JarsOptionHandler(
          CmdLineParser parser, OptionDef option, Setter<? super File> setter) {
        super(
            new CollectionOptionHandler<File>(
                parser,
                option,
                setter,
                "JAR",
                new CollectionOptionHandler.ItemParser<File>() {
                  @Override
                  public File parse(String item) {
                    return new File(item);
                  }
                }));
      }
    }

    @Option(
        name = "-jars",
        usage = "A list of comma-separated jar files whose entries to add to the output jar.",
        handler = JarsOptionHandler.class)
    private List<File> jars = Lists.newArrayList();

    public static class PatternOptionHandler extends CollectionOptionHandler<Pattern> {
      public PatternOptionHandler(
          CmdLineParser parser, OptionDef option, Setter<? super Pattern> setter) {
        super(
            parser,
            option,
            setter,
            "PATTERN",
            new ItemParser<Pattern>() {
              @Override
              public Pattern parse(String item) {
                try {
                  return Pattern.compile(item);
                } catch (PatternSyntaxException e) {
                  throw new IllegalArgumentException(e);
                }
              }
            });
      }
    }

    @Option(
        name = "-skip",
        usage = "A list of regular expressions identifying entries to skip.",
        handler = PatternOptionHandler.class)
    private List<Pattern> skip = Lists.newArrayList();

    private static final String ACTIONS = "SKIP|REPLACE|CONCAT|CONCAT_TEXT|THROW";

    @Option(
        name = "-default_action",
        usage =
            "The default duplicate action to apply if no policies match. Can be any of " + ACTIONS)
    private DuplicateAction defaultAction = DuplicateAction.SKIP;

    @Option(
        name = "-policies",
        usage =
            "A list of duplicate policies to apply. Policies are specified as "
                + "[regex]=[action], and the action can be any one of "
                + ACTIONS
                + ". For example: ^META-INF/services/=CONCAT_TEXT would concatenate duplicate"
                + " service files into one large service file.",
        handler = DuplicatePolicyParser.class)
    private List<DuplicatePolicy> policies = Lists.newArrayList();

    @Argument(metaVar = "TARGET_JAR", usage = "The target jar file path to write.", required = true)
    private File targetJar;
  }

  private static final Logger LOG = Logger.getLogger(Main.class.getName());

  private static class LoggingListener implements Listener {
    private Source source = null;
    private final File target;

    LoggingListener(File target) {
      this.target = target;
    }

    @Override
    public void onSkip(Optional<? extends Entry> original, Iterable<? extends Entry> skipped) {
      if (LOG.isLoggable(Level.FINE)) {
        if (original.isPresent()) {
          LOG.fine(
              String.format(
                  "Retaining %s and skipping %s", identify(original.get()), identify(skipped)));
        } else {
          LOG.fine(String.format("Skipping %s", identify(skipped)));
        }
      }
    }

    @Override
    public void onReplace(Iterable<? extends Entry> originals, Entry replacement) {
      if (LOG.isLoggable(Level.FINE)) {
        LOG.fine(
            String.format("Using %s to replace %s", identify(replacement), identify(originals)));
      }
    }

    @Override
    public void onConcat(String entryName, Iterable<? extends Entry> entries) {
      if (LOG.isLoggable(Level.FINE)) {
        LOG.fine(
            String.format(
                "Concatenating %s!%s from %s", target.getPath(), entryName, identify(entries)));
      }
    }

    @Override
    public void onWrite(Entry entry) {
      if (!entry.getSource().equals(source)) {
        source = entry.getSource();
        LOG.fine(entry.getSource().name());
      }
      LOG.log(Level.FINER, "\t{0}", entry.getName());
    }

    private static String identify(Entry entry) {
      return entry.getSource().identify(entry.getName());
    }

    private static String identify(Iterable<? extends Entry> entries) {
      return Joiner.on(",")
          .join(
              FluentIterable.from(entries)
                  .transform(
                      new Function<Entry, String>() {
                        @Override
                        public String apply(Entry input) {
                          return identify(input);
                        }
                      }));
    }
  }

  private final Options options;

  private Main(Options options) {
    this.options = options;
  }

  static class ExitException extends Exception {
    private final int code;

    ExitException(int code, String message, Object... args) {
      super(String.format(message, args));
      this.code = code;
    }
  }

  private void run() throws ExitException {
    if (options.mainClass != null && options.manifest != null) {
      throw new ExitException(1, "Can specify main or manifest but not both.");
    }
    if (!options.update && options.targetJar.exists() && !options.targetJar.delete()) {
      throw new ExitException(
          1, "Failed to delete file at requested target path %s", options.targetJar);
    }

    final Closer closer = Closer.create();
    try {
      doRun(closer, options.targetJar);
    } finally {
      try {
        closer.close();
      } catch (IOException e) {
        LOG.warning("Failed to close one or more resources: " + e);
      }
    }
  }

  private void doRun(Closer closer, final File targetJar) throws ExitException {
    JarBuilder jarBuilder =
        closer.register(new JarBuilder(targetJar, new LoggingListener(targetJar)));

    try {
      @Nullable Manifest mf = getManifest();
      if (mf != null) {
        jarBuilder.useCustomManifest(mf);
      }
    } catch (IOException e) {
      throw new ExitException(1, "Failed to configure custom manifest: %s", e);
    }

    for (Options.FileSource fileSource : options.files) {
      fileSource.addTo(jarBuilder);
    }

    for (File jar : options.jars) {
      jarBuilder.addJar(jar);
    }

    DuplicateHandler duplicateHandler =
        new DuplicateHandler(options.defaultAction, options.policies);
    try {
      jarBuilder.write(options.compress, duplicateHandler, options.skip);
    } catch (DuplicateEntryException e) {
      throw new ExitException(1, "Refusing to write duplicate entry: %s", e);
    } catch (IOException e) {
      throw new ExitException(1, "Unexpected problem writing target jar %s: %s", targetJar, e);
    }
  }

  private static final Splitter CLASS_PATH_SPLITTER =
      Splitter.on(File.pathSeparatorChar).omitEmptyStrings();

  private static final Function<String, Iterable<String>> ENTRY_TO_PATHS =
      new Function<String, Iterable<String>>() {
        @Override
        public Iterable<String> apply(String entry) {
          return CLASS_PATH_SPLITTER.split(entry);
        }
      };

  private static final Joiner CLASS_PATH_JOINER = Joiner.on(' ');

  @Nullable
  private Manifest getManifest() throws IOException {
    if (options.manifest == null && options.mainClass == null && options.classPath == null) {
      return null;
    }

    Manifest mf = loadManifest();
    if (options.mainClass != null) {
      mf.getMainAttributes().put(Name.MAIN_CLASS, options.mainClass);
    }
    if (options.classPath != null) {
      String classpath =
          CLASS_PATH_JOINER.join(
              FluentIterable.from(options.classPath).transformAndConcat(ENTRY_TO_PATHS));
      mf.getMainAttributes().put(Name.CLASS_PATH, classpath);
    }
    return mf;
  }

  private Manifest loadManifest() throws IOException {
    Manifest mf = new Manifest();
    if (options.manifest != null) {
      Closer closer = Closer.create();
      try {
        FileInputStream input = closer.register(new FileInputStream(options.manifest));
        mf.read(input);
      } catch (IOException e) {
        throw closer.rethrow(
            new IOException("Failed to load manifest from " + options.manifest, e));
      } finally {
        closer.close();
      }
    }
    return JarBuilder.ensureDefaultManifestEntries(mf);
  }

  /**
   * Creates or updates a jar with specified files, directories and jar files.
   *
   * @param args The command line arguments.
   */
  public static void main(String[] args) {
    ConsoleHandler handler = new ConsoleHandler();
    handler.setFormatter(new SimpleFormatter());
    handler.setLevel(Level.WARNING);
    Logger.getLogger("").addHandler(handler);

    Options options = new Options();

    Parser.Result result = Parser.parse(options, args);
    if (result.isFailure()) {
      result.printUsage(System.err);
      exit(1);
    } else if (options.help) {
      result.printUsage(System.out);
      exit(0);
    }

    Main main = new Main(options);
    try {
      main.run();
    } catch (ExitException e) {
      System.err.println(e.getMessage());
      exit(e.code);
    }
    exit(0);
  }

  private static void exit(int code) {
    // We're a main - its fine to exit.
    // SUPPRESS CHECKSTYLE RegexpSinglelineJava
    System.exit(code);
  }
}
