// Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
// Licensed under the Apache License, Version 2.0 (see LICENSE).

package org.pantsbuild.tools.compiler;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.EnumSet;
import java.util.Iterator;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

import javax.tools.Diagnostic;
import javax.tools.Diagnostic.Kind;
import javax.tools.FileObject;
import javax.tools.JavaCompiler;
import javax.tools.JavaCompiler.CompilationTask;
import javax.tools.JavaFileManager;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;

import org.pantsbuild.tools.compiler.DiagnosticFilters.DiagnosticFilter;
import org.pantsbuild.tools.compiler.DiagnosticFilters.Guard;

/**
 * A simple dependency tracking compiler that maps generated classes to the owning sources.
 *
 * Supports a <pre>-Tdependencyfile</pre> option to output dependency information to in the form:
 * <pre>
 * [source file path] -&gt; [class file path]
 * </pre>
 *
 * There may be multiple lines per source file if the file contains multiple top level classes or
 * inner classes.  All paths are normalized to be relative to the classfile output directory.
 *
 * Also supports warning customizations including:
 * <ul>
 *   <li><pre>-Tcolor</pre> To turn on colorized console output.
 *   <li><pre>-Tnowarnprefixes</pre> Path prefixes to skip warnings for, multiple can be separated
 *   with the system path separator and the flag itself can be passed multiple times.
 *   <li><pre>-Tnowarnregex</pre> Regex to apply to warning messages.  Matches are not warned and
 *   the flag can be massed multiple times to specify several regexs.
 * </ul>
 */
// SUPPRESS CHECKSTYLE HideUtilityClassConstructor
public final class Compiler {

  public static final String DEPENDENCYFILE_FLAG = "-Tdependencyfile";
  public static final String COLOR_FLAG = "-Tcolor";
  public static final String WARN_IGNORE_PATH_PREFIXES = "-Tnowarnprefixes";
  public static final String WARN_IGNORE_MESSAGE_REGEX = "-Tnowarnregex";

  /**
   * Should not be used; instead invoke {@link #main} directly.  Only present to conform to
   * a common compiler interface idiom expected by jmake.
   */
  public Compiler() {
  }

  /**
   * Handles parsing args for the compiler.
   */
  static class ArgParser {
    private static final Set<Kind> WARNING_KINDS = EnumSet.of(Kind.WARNING, Kind.MANDATORY_WARNING);
    private static final Guard<Diagnostic<? extends FileObject>> IS_WARNING =
        new Guard<Diagnostic<? extends FileObject>>() {
          @Override public boolean permit(Diagnostic<? extends FileObject> diagnostic) {
            return WARNING_KINDS.contains(diagnostic.getKind());
          }
        };

    private final JavaCompiler compiler;
    private final FilteredDiagnosticListener<? extends FileObject> diagnosticListener;
    private final StandardJavaFileManager standardFileManager;

    private final List<String> options = new ArrayList<String>();
    private final List<String> compilationUnits = new ArrayList<String>();
    private File dependencyFile;
    private boolean color;

    ArgParser(JavaCompiler compiler,
        FilteredDiagnosticListener<? extends FileObject> diagnosticListener,
        StandardJavaFileManager standardFileManager) {

      this.compiler = compiler;
      this.diagnosticListener = diagnosticListener;
      this.standardFileManager = standardFileManager;
    }

    void parse(String[] args) {
      List<DiagnosticFilter<? super FileObject>> filters =
          new ArrayList<DiagnosticFilter<? super FileObject>>();

      List<String> pathPrefixes = new ArrayList<String>();
      List<Pattern> messageRegexes = new ArrayList<Pattern>();

      for (Iterator<String> iter = Arrays.asList(args).iterator(); iter.hasNext();) {
        String arg = iter.next();
        if (DEPENDENCYFILE_FLAG.equals(arg)) {
          parseDependencyFile(iter);
        } else if (COLOR_FLAG.equals(arg)) {
          color = true;
        } else if (WARN_IGNORE_PATH_PREFIXES.equals(arg)) {
          pathPrefixes.addAll(parsePrefixes(iter));
        } else if (WARN_IGNORE_MESSAGE_REGEX.equals(arg)) {
          messageRegexes.add(parseRegex(iter));
        } else if (arg.startsWith("-")) {
          parsePassThroughOption(arg, iter);
        } else {
          compilationUnits.add(arg);
        }
      }

      if (!pathPrefixes.isEmpty()) {
        filters.add(DiagnosticFilters.guarded(
            DiagnosticFilters.ignorePathPrefixes(pathPrefixes), IS_WARNING));
      }
      if (!messageRegexes.isEmpty()) {
        filters.add(DiagnosticFilters.guarded(
            DiagnosticFilters.ignoreMessagesMatching(messageRegexes), IS_WARNING));
      }

      if (!filters.isEmpty()) {
        diagnosticListener.setFilter(DiagnosticFilters.combine(filters));
      }
    }

    private void parseDependencyFile(Iterator<String> iter) {
      if (!iter.hasNext()) {
        throw new IllegalArgumentException(
            String.format("%s requires an argument specifying the output path",
                DEPENDENCYFILE_FLAG));
      }
      dependencyFile = new File(iter.next());
    }

    private Collection<String> parsePrefixes(Iterator<String> iter) {
      if (!iter.hasNext()) {
        throw new IllegalArgumentException(
            String.format("%s requires an argument specifying path prefixes to ignore",
                WARN_IGNORE_PATH_PREFIXES));
      }
      return Arrays.asList(iter.next().split(File.pathSeparator));
    }

    private Pattern parseRegex(Iterator<String> iter) {
      if (!iter.hasNext()) {
        throw new IllegalArgumentException(
            String.format("%s requires an argument specifying a warning message regex",
                WARN_IGNORE_MESSAGE_REGEX));
      }
      return Pattern.compile(iter.next());
    }

    private void parsePassThroughOption(String arg, Iterator<String> iter) {
      int argCount = compiler.isSupportedOption(arg);
      if (argCount == -1) {
        argCount = standardFileManager.isSupportedOption(arg);
      }
      if (argCount == -1) {
        System.err.println("WARNING: Skipping unsupported option " + arg);
      } else {
        options.add(arg);
        while (argCount-- > 0) {
          if (iter.hasNext()) {
            options.add(iter.next());
          }
        }
      }
    }

    List<String> getOptions() {
      return options;
    }

    List<String> getCompilationUnits() {
      return compilationUnits;
    }

    File getDependencyFile() {
      return dependencyFile;
    }

    boolean isColor() {
      return color;
    }
  }

  /**
   * Passes through all args to the system java compiler and tracks classes generated for each
   * source file.
   *
   * @param args The command line arguments.
   * @return An exit code where 0 indicates successful compilation.
   */
  public static int compile(String[] args) {
    try {
      return doCompile(args);
    // We want a controlled exit.
    // SUPPRESS CHECKSTYLE RegexpSinglelineJava
    } catch (Throwable t) {
      System.err.println("Unexpected compilation error:");
      t.printStackTrace(System.err);
      return 1;
    }
  }

  private static int doCompile(String[] args) throws IOException {
    AnsiColorDiagnosticListener<FileObject> diagnosticListener =
        new AnsiColorDiagnosticListener<FileObject>();

    JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
    StandardJavaFileManager standardFileManager =
        compiler.getStandardFileManager(
            diagnosticListener,
            null /* default locale */,
            null /* default charset */);

    ArgParser argParser = new ArgParser(compiler, diagnosticListener, standardFileManager);
    try {
      argParser.parse(args);
    } catch (IllegalArgumentException e) {
      System.err.println(e.getMessage());
      return 1;
    }

    diagnosticListener.setIncludeSourceInfo(getJavaVersion() >= 7);
    diagnosticListener.prepareConsole(argParser.isColor());
    try {
      JavaFileManager fileManager = standardFileManager;
      File dependencyFile = argParser.getDependencyFile();
      if (dependencyFile != null) {
        fileManager = new DependencyTrackingFileManager(standardFileManager, dependencyFile);
      }

      try {
        CompilationTask compilationTask =
            compiler.getTask(
                null, // default output stream
                fileManager,
                diagnosticListener,
                argParser.getOptions(),
                null, // we specify no custom annotation processors manually here
                standardFileManager.getJavaFileObjectsFromStrings(argParser.getCompilationUnits()));

        boolean success = compilationTask.call();
        return success ? 0 : 1;
      } finally {
        fileManager.close();
      }
    } finally {
      diagnosticListener.releaseConsole();
    }
  }

  private static int getJavaVersion() {
    String version = System.getProperty("java.version");
    String[] components = version.split("\\.", 3);
    return Integer.parseInt(components[1]);
  }

  /**
   * Passes through all args to the system java compiler and tracks classes generated for each
   * source file.
   *
   * @param args The command line arguments.
   */
  public static void main(String[] args) {
    exit(compile(args));
  }

  private static void exit(int code) {
    // We're a main - its fine to exit.
    // SUPPRESS CHECKSTYLE RegexpSinglelineJava
    System.exit(code);
  }
}
