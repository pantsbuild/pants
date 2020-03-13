/**
  * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
  */
package org.pantsbuild.zinc.compiler

import java.io.{File, PrintWriter}
import java.nio.file.Paths
import scala.collection.JavaConverters._
import scala.compat.java8.OptionConverters._
import sbt.internal.inc.IncrementalCompilerImpl
import sbt.internal.util.{BasicLogger, ConsoleLogger, ConsoleOut, StackTrace}
import sbt.io.IO
import sbt.util.{ControlEvent, Level, LogEvent, Logger}
import xsbti.CompileFailed
import xsbti.compile.Inputs
import xsbti.{Problem, Severity}
import com.martiansoftware.nailgun.NGContext
import com.google.gson.Gson
import com.google.common.base.Charsets
import com.google.common.io.Files
import org.eclipse.lsp4j.{
  Diagnostic,
  DiagnosticSeverity,
  Position,
  PublishDiagnosticsParams,
  Range
}
import org.pantsbuild.zinc.analysis.AnalysisMap
import org.pantsbuild.zinc.util.Util

// TODO: why does the default logger take so long? Is it scanning the filesystem or doing something
// else pathological?
// The normal sbt logger takes 5 seconds to start up in a native image. This is intended to be
// equivalent, while allowing the native image to run immediately.
case class BareBonesLogger(thisLevel: Level.Value) extends BasicLogger {
  import scala.Console.{CYAN, GREEN, RED, YELLOW, RESET}

  val out = System.err

  override def trace(t: => Throwable): Unit =
    out.println(StackTrace.trimmed(t, getTrace))

  override def success(message: => String): Unit = {
    val colored = s"$GREEN[success!] $message$RESET"
    out.println(colored)
  }

  def printError(message: => String): Unit = {
    val colored = s"$RED[error] $message$RESET"
    out.println(colored)
  }

  override def log(
      level: Level.Value,
      message: => String
  ): Unit = {
    if (level >= thisLevel) {
      val (colorStart, prefix) = level match {
        case Level.Debug => (CYAN, "[debug]")
        case Level.Info  => (GREEN, "[info]")
        case Level.Warn  => (YELLOW, "[warn]")
        case Level.Error => (RED, "[error]")
      }
      val colored = s"$colorStart$prefix $message$RESET"
      out.println(colored)
    }
  }

  override def logAll(events: Seq[LogEvent]): Unit = events.foreach(log)

  // TODO: Figure out what messages get routed to this method!
  override def control(event: ControlEvent.Value, message: => String): Unit = {
    val colored = s"$GREEN[control: $event] $message$RESET"
    out.println(colored)
  }
}

/**
  * Command-line main class.
  */
object Main {

  /**
    * Full zinc version info.
    */
  case class Version(published: String, timestamp: String, commit: String)

  /**
    * Get the zinc version from a generated properties file.
    */
  lazy val zincVersion: Version = {
    val props = Util.propertiesFromResource("zinc.version.properties",
                                            getClass.getClassLoader)
    Version(
      props.getProperty("version", "unknown"),
      props.getProperty("timestamp", ""),
      props.getProperty("commit", "")
    )
  }

  /**
    * For snapshots the zinc version includes timestamp and commit.
    */
  lazy val versionString: String = {
    import zincVersion._
    if (published.endsWith("-SNAPSHOT"))
      "%s %s-%s" format (published, timestamp, commit take 10)
    else published
  }

  def mkLogger(settings: Settings) = {
    // If someone has not explicitly enabled log4j2 JMX, disable it.
    if (!Util.isSetProperty("log4j2.disable.jmx")) {
      Util.setProperty("log4j2.disable.jmx", "true")
    }

    // As per https://github.com/pantsbuild/pants/issues/6160, this is a workaround
    // so we can run zinc without $PATH (as needed in remoting).
    System.setProperty("sbt.log.format", "true")

    def mkConsoleLogger(level: Level.Value, color: Boolean): ConsoleLogger = {
      val cl =
        ConsoleLogger(out = ConsoleOut.systemOut, ansiCodesSupported = color)
      cl.setLevel(level)
      cl
    }

    if (settings.consoleLog.useBarebonesLogger) {
      BareBonesLogger(settings.consoleLog.logLevel)
    } else {
      mkConsoleLogger(settings.consoleLog.logLevel, settings.consoleLog.color)
    }
  }

  def preprocessArgs(rawArgs: Array[String]): Array[String] = {
    val (argFiles, partialArgs) = rawArgs.partition(_.startsWith("@"))
    val args = partialArgs ++ argFiles.flatMap { f =>
      Files.readLines(new File(f.drop(1)), Charsets.UTF_8).asScala
    }
    val fixedArgs = args.flatMap { arg =>
      arg match {
        case x if x.startsWith("-C") || x.startsWith("-S") => {
          val tup = arg.splitAt(2)
          Seq(tup._1, tup._2)
        }
        case arg => Seq(arg)
      }
    }
    for (i <- 1 to fixedArgs.size) {
      // Because we set -cp as the shorthand for classpath, we can't also set -classpath as one.
      // Fix it up.
      if (fixedArgs(i - 1) == "-classpath") {
        fixedArgs(i - 1) = "--classpath"
      }
      // Old versions of this binary used :s not ,s as list separators.
      // Accept their input.
      if (fixedArgs(i - 1) == "--classpath" || fixedArgs(i - 1) == "-cp"
          || fixedArgs(i - 1) == "--scala-path" || fixedArgs(i - 1) == "-scala-path") {
        fixedArgs(i) = fixedArgs(i).replace(":", ",")
      }
      // Old versions of this binary used :s not =s as map separators.
      // Accept their input.
      if (fixedArgs(i - 1) == "--analysis-map" || fixedArgs(i - 1) == "-analysis-map") {
        fixedArgs(i) = fixedArgs(i).replace(":", "=")
      }
    }
    fixedArgs
  }

  /**
    * Run a compile.
    */
  def main(args: Array[String]): Unit = {
    val startTime = System.currentTimeMillis

    val settings =
      Settings.SettingsParser.parse(preprocessArgs(args), Settings()) match {
        case Some(settings) => settings
        case None => {
          println("See zinc-compiler --help for information about options")
          sys.exit(1)
        }
      }

    val workingDirectory = Paths.get(".").toAbsolutePath.toFile
    mainImpl(
      settings.withAbsolutePaths(workingDirectory),
      startTime,
      n => sys.exit(1),
      workingDirectory
    )
  }

  def nailMain(context: NGContext): Unit = {
    val startTime = System.currentTimeMillis

    Settings.SettingsParser
      .parse(preprocessArgs(context.getArgs), Settings()) match {
      case Some(settings) =>
        val workingDirectory = new File(context.getWorkingDirectory)
        mainImpl(
          settings.withAbsolutePaths(workingDirectory),
          startTime,
          n => context.exit(n),
          workingDirectory
        )
      case None => {
        println("See zinc-compiler --help for information about options")
        context.exit(1)
      }
    }
  }

  def toLsp(severity: Severity): DiagnosticSeverity = {
    severity match {
      case Severity.Error => DiagnosticSeverity.Error
      case Severity.Warn  => DiagnosticSeverity.Warning
      case Severity.Info  => DiagnosticSeverity.Information
      // Note: DiagnosticSeverity also has a Hint level, but we won't use it here as xsbti doesn't go that far
    }
  }
  def toZeroBased(x: Int): Int = {
    x - 1
  }
  def toUri(file: File): java.net.URI = {
    file.getAbsoluteFile().toPath().toUri()
  }
  def toLsp(problems: List[Problem],
            workingDirectory: File): Array[PublishDiagnosticsParams] = {
    import scala.tools.nsc.io.Path._
    problems
      .groupBy(problem => problem.position.sourcePath)
      .map {
        case (file, problems) => {
          val uri: String =
            file.asScala
              .map(filePath => {
                val rootUri = toUri(workingDirectory)
                val fileUri = toUri(new File(filePath))
                rootUri.relativize(fileUri)
              })
              .map(relativePath => "buildroot://" + relativePath.toString())
              // Note: while zinc allows the sourcePath to be optional, the LSP enforces an existing
              // URI. For this reason, we use an empty URI to represent the case where the URI would
              // be missing from the zinc's output.
              .getOrElse("")

          val diagnostics =
            problems
              .map(problem => {
                val position =
                  new Position(
                    // xsbti uses one-based values for line and "pointer" (i.e: character index)
                    // the Language ServerProtocol requires zero-based values
                    toZeroBased(problem.position.line.orElse(0)),
                    toZeroBased(problem.position.pointer.orElse(0))
                  )

                val range = new Range(position, position)
                val severity = toLsp(problem.severity)
                val code = problem.category()
                new Diagnostic(range, problem.message(), severity, "zinc", code)
              })
          new PublishDiagnosticsParams(uri, diagnostics.asJava)
        }
      }.toArray
  }

  def dumpDiagnostics(diagnosticsFile: File,
                      inputs: Inputs,
                      workingDirectory: File,
                      log: Logger): Unit = {
    val problems = inputs.setup.reporter.problems.toList
    val serializer = new Gson()
    val serialized = serializer.toJson(toLsp(problems, workingDirectory))
    log.debug(
      "Writing diagnostics report to file: " + diagnosticsFile.toString
    )
    val writer = new PrintWriter(diagnosticsFile)
    try {
      writer.write(serialized)
    } finally {
      writer.close()
    }
  }

  def mainImpl(settings: Settings,
               startTime: Long,
               exit: Int => Unit,
               workingDirectory: File): Unit = {
    val log = mkLogger(settings)
    val isDebug = settings.consoleLog.logLevel <= Level.Debug

    // if there are no sources provided, print outputs based on current analysis if requested,
    // else print version and usage by default
    if (settings.sources.isEmpty) {
      exit(1)
    }

    // Load the existing analysis for the destination, if any.
    val analysisMap = AnalysisMap.create(settings.analysis)
    val (targetAnalysisStore, previousResult) =
      InputUtils.loadDestinationAnalysis(settings, analysisMap, log)
    val inputs = InputUtils.create(settings, analysisMap, previousResult, log)

    if (isDebug) {
      log.debug(s"Inputs: $inputs")
    }

    try {
      // Run the compile.
      val result = new IncrementalCompilerImpl().compile(inputs, log)

      // post compile merge dir
      if (settings.postCompileMergeDir.isDefined) {
        IO.copyDirectory(
          new File(settings.postCompileMergeDir.get.toURI),
          new File(settings.classesDirectory.toURI)
        )
      }

      // Store the output if the result changed.
      if (result.hasModified) {
        targetAnalysisStore.set(
          // TODO
          sbt.internal.inc
            .ConcreteAnalysisContents(result.analysis, result.setup)
        )
      }
      log.info("Compile success " + Util.timing(startTime))
      // if compile is successful, jar the contents of classesDirectory and copy to outputJar
      if (settings.outputJar.isDefined) {
        val outputJarPath = settings.outputJar.get.toPath
        val classesDirectory = settings.classesDirectory
        log.debug(
          "Creating JAR at %s, for files at %s" format (outputJarPath, classesDirectory))
        OutputUtils.createClassesJar(classesDirectory,
                                     outputJarPath,
                                     settings.creationTime)
      }
    } catch {
      case e: CompileFailed =>
        log.error("Compile failed " + Util.timing(startTime))
        exit(1)
      case e: Exception =>
        if (isDebug) e.printStackTrace
        val message = e.getMessage
        if (message ne null) log.error(message)
        exit(1)
    } finally {
      settings.diagnosticsOut.map(diagnosticsFile => {
        dumpDiagnostics(diagnosticsFile, inputs, workingDirectory, log)
      })
    }
  }
}
