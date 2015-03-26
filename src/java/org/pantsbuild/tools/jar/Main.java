// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.jar;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.lang.reflect.Type;
import java.util.Arrays;
import java.util.List;
import java.util.jar.Attributes.Name;
import java.util.jar.Manifest;
import java.util.logging.Level;
import java.util.logging.Logger;
import java.util.regex.Pattern;

import javax.annotation.Nullable;

import com.google.common.base.Function;
import com.google.common.base.Joiner;
import com.google.common.base.Optional;
import com.google.common.base.Preconditions;
import com.google.common.base.Splitter;
import com.google.common.collect.FluentIterable;
import com.google.common.collect.ImmutableList;
import com.google.common.collect.ImmutableSet;
import com.google.common.collect.Iterables;
import com.google.common.io.Closer;
import com.google.common.reflect.TypeToken;

import com.twitter.common.args.Arg;
import com.twitter.common.args.ArgParser;
import com.twitter.common.args.ArgScanner;
import com.twitter.common.args.Args;
import com.twitter.common.args.Args.ArgsInfo;
import com.twitter.common.args.CmdLine;
import com.twitter.common.args.Parser;
import com.twitter.common.args.ParserOracle;
import com.twitter.common.args.Positional;
import com.twitter.common.args.constraints.CanRead;
import com.twitter.common.args.constraints.Exists;
import com.twitter.common.base.MorePreconditions;
import org.pantsbuild.tools.jar.tool.JarBuilder.DuplicateAction;
import org.pantsbuild.tools.jar.tool.JarBuilder.DuplicateEntryException;
import org.pantsbuild.tools.jar.tool.JarBuilder.DuplicateHandler;
import org.pantsbuild.tools.jar.tool.JarBuilder.DuplicatePolicy;
import org.pantsbuild.tools.jar.tool.JarBuilder.Entry;
import org.pantsbuild.tools.jar.tool.JarBuilder.Listener;
import org.pantsbuild.tools.jar.tool.JarBuilder.Source;
import com.twitter.common.logging.RootLogConfig;
import com.twitter.common.logging.RootLogConfig.LogLevel;

public final class Main {
  @ArgParser
  static class DuplicatePolicyParser implements Parser<DuplicatePolicy> {
    private static final Splitter REGEX_ACTION_SPLITTER =
        Splitter.on("=").trimResults().omitEmptyStrings();

    @Override
    public DuplicatePolicy parse(ParserOracle parserOracle, Type type, String raw)
        throws IllegalArgumentException {

      List<String> components = ImmutableList.copyOf(REGEX_ACTION_SPLITTER.split(raw));
      Preconditions.checkArgument(components.size() == 2,
          "Failed to parse jar path regex/action pair %s", raw);

      String regex = components.get(0);

      Parser<DuplicateAction> actionParser = parserOracle.get(TypeToken.of(DuplicateAction.class));
      DuplicateAction action =
          actionParser.parse(parserOracle, DuplicateAction.class, components.get(1));

      return DuplicatePolicy.pathMatches(regex, action);
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
        MorePreconditions.checkNotBlank(destination, "The destination path cannot be blank");
        Preconditions.checkArgument(
            !destination.startsWith("/"),
            "The destination path cannot be absolute, given: %s", destination);
        Preconditions.checkArgument(
            !ImmutableSet.copyOf(JAR_PATH_SPLITTER.split(destination)).contains(".."),
            "The destination path cannot be relative, given: %s", destination);
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
      return String.format("FileSource{source=%s, destination=%s}", source, destination);
    }
  }

  @ArgParser
  static class FileSourceParser implements Parser<FileSource> {
    private static final Splitter DESTINATION_SPLITTER =
        Splitter.on("=").trimResults().omitEmptyStrings();

    @Override
    public FileSource parse(ParserOracle parserOracle, Type type, String raw)
        throws IllegalArgumentException {

      List<String> components = ImmutableList.copyOf(DESTINATION_SPLITTER.split(raw));
      Preconditions.checkArgument(1 <= components.size() && components.size() <= 2,
          "Failed to parse entry %s", raw);

      File source = new File(components.get(0));
      @Nullable String destination = components.size() == 2 ? components.get(1) : null;
      return new FileSource(source, destination);
    }
  }

  @CmdLine(name = "main",
      help = "The name of the fully qualified main class. "
          + "If a -manifest is specified its contents will be used but this -main will override "
          + "any entry already present.")
  private final Arg<String> mainClass = Arg.create(null);

  @CmdLine(name = "classpath",
      help = "A list of comma-separated classpath entries. "
          + "If a -manifest is specified its contents will be used but this -classpath will "
          + "override any entry already present.",
      argFile = true)
  private final Arg<List<String>> classPath = Arg.create(null);

  @Exists
  @CanRead
  @CmdLine(name = "manifest",
      help = "A path to a manifest file to use. If -main or -classpath is specified those values "
          + "will overwrite the corresponding entry in this manifest.")
  private final Arg<File> manifest = Arg.create(null);

  @CmdLine(name = "update", help = "Update the jar if it already exists, otherwise create it.")
  private final Arg<Boolean> update = Arg.create(false);

  @CmdLine(name = "compress", help = "Compress jar entries.")
  private final Arg<Boolean> compress = Arg.create(false);

  @CmdLine(name = "files",
      help = "A mapping from filesystem paths to jar paths. The mapping is specified in the form "
          + "[fs path1](=[jar path1]),[fs path2](=[jar path2]). For example: "
          + "/etc/hosts=hosts,/var/log=logs would create a jar with a hosts file entry and the "
          + "contents of the /var/log tree added as individual entries under the logs/ directory "
          + "in the jar. For directories, the mapping can be skipped in which case the directory "
          + "tree is added as-is to the resulting jar.",
      argFile = true)
  private final Arg<List<FileSource>> files =
      Arg.<List<FileSource>>create(ImmutableList.<FileSource>of());

  @CmdLine(name = "jars",
      help = "A list of comma-separated jar files whose entries to add to the output jar.",
      argFile = true)
  private final Arg<List<File>> jars = Arg.<List<File>>create(ImmutableList.<File>of());

  @CmdLine(name = "skip", help = "A list of regular expressions identifying entries to skip.")
  private final Arg<List<Pattern>> skip = Arg.<List<Pattern>>create(ImmutableList.<Pattern>of());

  private static final String ACTIONS = "SKIP|REPLACE|CONCAT|THROW";

  @CmdLine(name = "default_action",
      help = "The default duplicate action to apply if no policies match. Can be any of "
          + ACTIONS)
  private final Arg<DuplicateAction> defaultAction = Arg.create(DuplicateAction.SKIP);

  @CmdLine(name = "policies",
      help = "A list of duplicate policies to apply. Policies are specified as [regex]=[action], "
          + "and the action can be any one of " + ACTIONS + ". For example: "
          + "^META-INF/services/=CONCAT would concatenate duplicate service files into one large "
          + "service file.")
  private final Arg<List<DuplicatePolicy>> policies =
      Arg.<List<DuplicatePolicy>>create(ImmutableList.<DuplicatePolicy>of());

  @Positional(help = "The target jar file path to write.")
  private final Arg<List<File>> target = Arg.create();

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
          LOG.fine(String.format("Retaining %s and skipping %s", identify(original.get()),
              identify(skipped)));
        } else {
          LOG.fine(String.format("Skipping %s", identify(skipped)));
        }
      }
    }

    @Override
    public void onReplace(Iterable<? extends Entry> originals, Entry replacement) {
      if (LOG.isLoggable(Level.FINE)) {
        LOG.fine(String.format("Using %s to replace %s", identify(replacement),
            identify(originals)));
      }
    }

    @Override
    public void onConcat(String entryName, Iterable<? extends Entry> entries) {
      if (LOG.isLoggable(Level.FINE)) {
        LOG.fine(String.format("Concatenating %s!%s from %s", target.getPath(), entryName,
            identify(entries)));
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
      return Joiner.on(",").join(
          FluentIterable.from(entries).transform(new Function<Entry, String>() {
            @Override public String apply(Entry input) {
              return identify(input);
            }
          }));
    }
  }

  private Main() {
    // tool
  }

  static class ExitException extends Exception {
    private final int code;

    ExitException(int code, String message, Object... args) {
      super(String.format(message, args));
      this.code = code;
    }
  }

  private void run() throws ExitException {
    if (mainClass.hasAppliedValue() && manifest.hasAppliedValue()) {
      throw new ExitException(1, "Can specify main or manifest but not both.");
    }
    if (target.get().size() != 1) {
      throw new ExitException(1, "Must supply exactly 1 target jar path.");
    }
    final File targetJar = Iterables.getOnlyElement(this.target.get());

    if (!update.get() && targetJar.exists() && !targetJar.delete()) {
      throw new ExitException(1, "Failed to delete file at requested target path %s", targetJar);
    }

    final Closer closer = Closer.create();
    try {
      doRun(closer, targetJar);
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

    for (FileSource fileSource : files.get()) {
      fileSource.addTo(jarBuilder);
    }

    for (File jar : jars.get()) {
      jarBuilder.addJar(jar);
    }

    DuplicateHandler duplicateHandler = new DuplicateHandler(defaultAction.get(), policies.get());
    try {
      jarBuilder.write(compress.get(), duplicateHandler, skip.get());
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
        @Override public Iterable<String> apply(String entry) {
          return CLASS_PATH_SPLITTER.split(entry);
        }
      };

  private static final Joiner CLASS_PATH_JOINER = Joiner.on(' ');

  @Nullable
  private Manifest getManifest() throws IOException {
    if (!manifest.hasAppliedValue()
        && !mainClass.hasAppliedValue()
        && !classPath.hasAppliedValue()) {

      return null;
    }

    Manifest mf = loadManifest();
    if (mainClass.hasAppliedValue()) {
      mf.getMainAttributes().put(Name.MAIN_CLASS, mainClass.get());
    }
    if (classPath.hasAppliedValue()) {
      String classpath =
          CLASS_PATH_JOINER.join(
              FluentIterable.from(classPath.get()).transformAndConcat(ENTRY_TO_PATHS));
      mf.getMainAttributes().put(Name.CLASS_PATH, classpath);
    }
    return mf;
  }

  private Manifest loadManifest() throws IOException {
    Manifest mf = new Manifest();
    if (this.manifest.hasAppliedValue()) {
      Closer closer = Closer.create();
      try {
        FileInputStream input = closer.register(new FileInputStream(this.manifest.get()));
        mf.read(input);
      } catch (IOException e) {
        throw closer.rethrow(
            new IOException("Failed to load manifest from " + this.manifest.get(), e));
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
    RootLogConfig.builder()
        .logToStderr(true)
        .useGLogFormatter(true)
        .vlog(LogLevel.WARNING)
        .build()
        .apply();

    Main main = new Main();
    try {
      ArgsInfo argsInfo = Args.from(main);
      if (!new ArgScanner().parse(argsInfo, Arrays.asList(args))) {
        exit(1);
      }
    } catch (IOException e) {
      System.err.printf("Failed to load argument info: %s\n", e);
      exit(1);
    }

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
