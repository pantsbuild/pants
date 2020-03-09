/**
  * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
  */
package org.pantsbuild.zinc.compiler

import com.google.common.base.Joiner
import java.io.File
import java.nio.file.{Files, Path}
import java.lang.{Boolean => JBoolean}
import java.util.function.{Function => JFunction}
import java.util.{List => JList, logging => jlogging}
import scala.collection.JavaConverters._
import scala.compat.java8.OptionConverters._
import scala.util.matching.Regex
import sbt.io.syntax._
import sbt.util.{Level, Logger}
import xsbti.compile.{
  ClassFileManagerType,
  CompileOrder,
  TransactionalManagerType
}
import xsbti.compile.{IncOptions => ZincIncOptions}
import org.pantsbuild.zinc.analysis.AnalysisOptions
import org.pantsbuild.zinc.util.Util

/**
  * All parsed command-line options.
  */
case class Settings(
    consoleLog: ConsoleOptions = ConsoleOptions(),
    _sources: Seq[File] = Seq.empty,
    classpath: Seq[File] = Seq.empty,
    _classesDirectory: Option[File] = None,
    _postCompileMergeDir: Option[File] = None,
    outputJar: Option[File] = None,
    scala: ScalaLocation = ScalaLocation(),
    diagnosticsOut: Option[File] = None,
    scalacOptions: Seq[String] = Seq.empty,
    javaHome: Option[File] = None,
    javaOnly: Boolean = false,
    javacOptions: Seq[String] = Seq.empty,
    compileOrder: CompileOrder = CompileOrder.Mixed,
    _incOptions: IncOptions = IncOptions(),
    analysis: AnalysisOptions = AnalysisOptions(),
    creationTime: Long = 0,
    compiledBridgeJar: Option[File] = None,
    useBarebonesLogger: Boolean = false
) {
  import Settings._

  lazy val sources: Seq[File] = _sources map normalise

  lazy val classesDirectory: File =
    normalise(_classesDirectory.getOrElse(defaultClassesDirectory()))

  lazy val postCompileMergeDir: Option[File] =
    _postCompileMergeDir.map(normalise)

  lazy val incOptions: IncOptions = {
    _incOptions.copy(
      apiDumpDirectory = _incOptions.apiDumpDirectory map normalise,
      backup = {
        if (_incOptions.transactional)
          Some(
            normalise(_incOptions.backup.getOrElse(
              defaultBackupLocation(classesDirectory))))
        else
          None
      }
    )
  }

  def withAbsolutePaths(relativeTo: File): Settings = {
    def normaliseSeq(seq: Seq[File]): Seq[File] =
      Util.normaliseSeq(Some(relativeTo))(seq)
    def normaliseOpt(opt: Option[File]): Option[File] =
      Util.normaliseOpt(Some(relativeTo))(opt)

    // It's a shame that this is manually listing the args which are files, but this doesn't feel
    // high-value enough to fold into the full options parsing
    // (which we may delete at some point anyway)...
    this.copy(
      _sources = normaliseSeq(_sources),
      classpath = normaliseSeq(classpath),
      _classesDirectory = normaliseOpt(_classesDirectory),
      outputJar = normaliseOpt(outputJar),
      scala = scala.withAbsolutePaths(relativeTo),
      diagnosticsOut = normaliseOpt(diagnosticsOut),
      javaHome = normaliseOpt(javaHome),
      _incOptions = _incOptions.withAbsolutePaths(relativeTo),
      analysis = analysis.withAbsolutePaths(relativeTo),
      compiledBridgeJar = normaliseOpt(compiledBridgeJar)
    )
  }
}

/**
  * Console logging options.
  */
case class ConsoleOptions(
    logLevel: Level.Value = Level.Info,
    color: Boolean = true,
    fileFilters: Seq[Regex] = Seq.empty,
    msgFilters: Seq[Regex] = Seq.empty,
    useBarebonesLogger: Boolean = false
) {
  def javaLogLevel: jlogging.Level = logLevel match {
    case Level.Info =>
      jlogging.Level.INFO
    case Level.Warn =>
      jlogging.Level.WARNING
    case Level.Error =>
      jlogging.Level.SEVERE
    case Level.Debug =>
      jlogging.Level.FINE
    case x =>
      sys.error(s"Unsupported log level: $x")
  }

  /**
    * Because filtering Path objects requires first converting to a String, we compose
    * the regexes into one predicate.
    */
  def filePredicates: Seq[JFunction[Path, JBoolean]] =
    Seq(
      new JFunction[Path, JBoolean] {
        def apply(path: Path) = {
          val pathStr = path.toString
          fileFilters.exists(_.findFirstIn(pathStr).isDefined)
        }
      }
    )

  def msgPredicates: Seq[JFunction[String, JBoolean]] =
    msgFilters.map { regex =>
      new JFunction[String, JBoolean] {
        def apply(msg: String) = regex.findFirstIn(msg).isDefined
      }
    }
}

/**
  * Alternative ways to locate the scala jars.
  */
case class ScalaLocation(
    home: Option[File] = None,
    path: Seq[File] = Seq.empty,
    compiler: Option[File] = None,
    library: Option[File] = None,
    extra: Seq[File] = Seq.empty
) {
  def withAbsolutePaths(relativeTo: File): ScalaLocation = {
    def normaliseSeq(seq: Seq[File]): Seq[File] =
      Util.normaliseSeq(Some(relativeTo))(seq)
    def normaliseOpt(opt: Option[File]): Option[File] =
      Util.normaliseOpt(Some(relativeTo))(opt)

    // It's a shame that this is manually listing the args which are files, but this doesn't feel
    // high-value enough to fold into the full options parsing
    // (which we may delete at some point anyway)...
    this.copy(
      home = normaliseOpt(home),
      path = normaliseSeq(path),
      compiler = normaliseOpt(compiler),
      library = normaliseOpt(library),
      extra = normaliseSeq(extra)
    )
  }
}

object ScalaLocation {

  /**
    * Java API for creating ScalaLocation.
    */
  def create(home: File,
             path: JList[File],
             compiler: File,
             library: File,
             extra: JList[File]): ScalaLocation =
    ScalaLocation(
      Option(home),
      path.asScala,
      Option(compiler),
      Option(library),
      extra.asScala
    )

  /**
    * Java API for creating ScalaLocation with scala home.
    */
  def fromHome(home: File) = ScalaLocation(home = Option(home))

  /**
    * Java API for creating ScalaLocation with scala path.
    */
  def fromPath(path: JList[File]) = ScalaLocation(path = path.asScala)
}

/**
  * Wrapper around incremental compiler options.
  */
case class IncOptions(
    transitiveStep: Int = ZincIncOptions.defaultTransitiveStep,
    recompileAllFraction: Double = ZincIncOptions.defaultRecompileAllFraction,
    relationsDebug: Boolean = ZincIncOptions.defaultRelationsDebug,
    apiDebug: Boolean = ZincIncOptions.defaultApiDebug,
    apiDiffContextSize: Int = ZincIncOptions.defaultApiDiffContextSize,
    apiDumpDirectory: Option[File] =
      ZincIncOptions.defaultApiDumpDirectory.asScala,
    transactional: Boolean = false,
    useZincFileManager: Boolean = true,
    backup: Option[File] = None
) {
  def options(log: Logger): ZincIncOptions =
    ZincIncOptions
      .create()
      .withTransitiveStep(transitiveStep)
      .withRecompileAllFraction(recompileAllFraction)
      .withRelationsDebug(relationsDebug)
      .withApiDebug(apiDebug)
      .withApiDiffContextSize(apiDiffContextSize)
      .withApiDumpDirectory(apiDumpDirectory.asJava)
      .withClassfileManagerType(classfileManager(log).asJava)
      .withUseCustomizedFileManager(useZincFileManager)

  def classfileManager(log: Logger): Option[ClassFileManagerType] =
    if (transactional && backup.isDefined)
      Some(TransactionalManagerType.create(backup.get, log))
    else
      None

  def withAbsolutePaths(relativeTo: File): IncOptions = {
    // It's a shame that this is manually listing the args which are files, but this doesn't feel
    // high-value enough to fold into the full options parsing
    // (which we may delete at some point anyway)...
    this.copy(
      apiDumpDirectory = Util.normaliseOpt(Some(relativeTo))(apiDumpDirectory),
      backup = Util.normaliseOpt(Some(relativeTo))(backup)
    )
  }
}

object Settings {
  val logLevels = Set("debug", "info", "warn", "error")

  val SettingsParser = new scopt.OptionParser[Settings]("zinc-compiler") {
    head("pants-zinc-compiler", "0.0.10")
    help("help").text("Prints this usage message")
    version("version").text("Print version")

    opt[File]("compiled-bridge-jar")
      .abbr("compiled-bridge-jar")
      .required()
      .valueName("<file>")
      .action((x, c) => c.copy(compiledBridgeJar = Some(x)))
      .text("Path to pre-compiled compiler interface.")

    opt[Long]("jar-creation-time")
      .abbr("jar-creation-time")
      .action((x, c) => c.copy(creationTime = x))
      .text("Creation timestamp for compiled jars, default is current time")

    opt[Unit]("debug")
      .abbr("debug")
      .action((x, c) =>
        c.copy(consoleLog = c.consoleLog.copy(logLevel = Level.Debug)))
      .text("Set log level for stdout to debug")

    opt[String]("log-level")
      .abbr("log-level")
      .valueName("level")
      // Allow multiple specifiers of this, and always use the last.
      .unbounded()
      .validate { level =>
        {
          if (logLevels.contains(level)) success
          else failure(s"Level must be one of $logLevels.")
        }
      }
      .action((x, c) =>
        c.copy(consoleLog = c.consoleLog.copy(logLevel = Level.withName(x))))
      .text(
        s"Set log level for stdout (${Joiner.on('|').join(logLevels.asJava)})")

    opt[Unit]("no-color")
      .abbr("no-color")
      .action((x, c) => c.copy(consoleLog = c.consoleLog.copy(color = false)))
      .text("No color in logging to stdout")

    opt[String]("msg-filter")
      .abbr("msg-filter")
      .valueName("<regex>")
      .unbounded()
      .action((x, c) =>
        c.copy(consoleLog =
          c.consoleLog.copy(msgFilters = c.consoleLog.msgFilters :+ x.r)))
      .text("Filter warning messages matching the given regex")

    opt[String]("file-filter")
      .abbr("file-filter")
      .valueName("<regex>")
      .unbounded()
      .action((x, c) =>
        c.copy(consoleLog =
          c.consoleLog.copy(fileFilters = c.consoleLog.fileFilters :+ x.r)))
      .text("Filter warning messages from filenames matching the given regex")

    opt[Unit]("use-barebones-logger")
      .abbr("use-barebones-logger")
      .action((x, c) =>
        c.copy(consoleLog = c.consoleLog.copy(useBarebonesLogger = true)))
      .text("Use our custom barebones logger instead of the sbt logger. This is an experimental feature that speeds up native-image startup times considerably.")

    opt[Seq[File]]("classpath")
      .abbr("cp")
      .action((x, c) => c.copy(classpath = x))
      .text("Specify the classpath")

    opt[File]("post-compile-merge-dir")
      .action((x, c) => c.copy(_postCompileMergeDir = Some(x)))
      .text("Directory to merge with compile outputs after compilation")

    opt[File]("class-destination")
      .abbr("d")
      .action((x, c) => c.copy(_classesDirectory = Some(x)))
      .text("Destination for compiled classes")

    opt[File]("jar-destination")
      .abbr("jar")
      .action((x, c) => c.copy(outputJar = Some(x)))
      .text("Jar destination for compiled classes")

    opt[File]("scala-home")
      .abbr("scala-home")
      .valueName("<directory>")
      .action((x, c) => c.copy(scala = c.scala.copy(home = Some(x))))
      .text("Scala home directory (for locating jars)")

    opt[Seq[File]]("scala-path")
      .abbr("scala-path")
      .valueName("<path>")
      .action((x, c) => c.copy(scala = c.scala.copy(path = x)))
      .text("Specify all Scala jars directly")

    opt[File]("scala-compiler")
      .abbr("scala-compiler")
      .valueName("<file>")
      .action((x, c) => c.copy(scala = c.scala.copy(compiler = Some(x))))
      .text("Specify Scala compiler jar directly")

    opt[File]("scala-library")
      .abbr("scala-library")
      .valueName("<file>")
      .action((x, c) => c.copy(scala = c.scala.copy(library = Some(x))))
      .text("Specify Scala library jar directly")

    opt[Seq[File]]("scala-extra")
      .abbr("scala-extra")
      .valueName("<path>")
      .action((x, c) => c.copy(scala = c.scala.copy(extra = x)))
      .text("Specify extra Scala jars directly")
    opt[File]("diagnostics-out")
      .abbr("diag")
      .action((x, c) => c.copy(diagnosticsOut = Some(x)))
      .text("File where the report of compilation errors and warnings will be written")

    opt[File]("java-home")
      .abbr("java-home")
      .valueName("<directory>")
      .action((x, c) => c.copy(javaHome = Some(x)))
      .text("Select javac home directory (and fork)")

    opt[String]("compile-order")
      .abbr("compile-order")
      .action((x, c) => c.copy(compileOrder = compileOrder(x)))
      .text("Compile order for Scala and Java sources")

    opt[Unit]("java-only")
      .abbr("java-only")
      .action((x, c) => c.copy(javaOnly = true))
      .text("Don't add scala library to classpath")

    opt[Int]("transitive-step")
      .abbr("transitive-step")
      .action((x, c) =>
        c.copy(_incOptions = c._incOptions.copy(transitiveStep = x)))
      .text("Steps before transitive closure")

    opt[Double]("recompile-all-fraction")
      .abbr("recompile-all-fraction")
      .validate { fraction =>
        {
          if (0 <= fraction && fraction <= 1) success
          else failure("recompile-all-fraction must be between 0 and 1")
        }
      }
      .action((x, c) =>
        c.copy(_incOptions = c._incOptions.copy(recompileAllFraction = x)))
      .text("Limit before recompiling all sources")

    opt[Unit]("debug-relations")
      .abbr("debug-relations")
      .action((x, c) =>
        c.copy(_incOptions = c._incOptions.copy(relationsDebug = true)))
      .text("Enable debug logging of analysis relations")

    opt[Unit]("debug-api")
      .abbr("debug-api")
      .action((x, c) =>
        c.copy(_incOptions = c._incOptions.copy(apiDebug = true)))
      .text("Enable analysis API debugging")

    opt[File]("api-dump")
      .abbr("api-dump")
      .valueName("directory")
      .action((x, c) =>
        c.copy(_incOptions = c._incOptions.copy(apiDumpDirectory = Some(x))))
      .text("Destination for analysis API dump")

    opt[Int]("api-diff-context-size")
      .abbr("api-diff-context-size")
      .action((x, c) =>
        c.copy(_incOptions = c._incOptions.copy(apiDiffContextSize = x)))
      .text("Diff context size (in lines) for API debug")

    opt[Unit]("transactional")
      .abbr("transactional")
      .action((x, c) =>
        c.copy(_incOptions = c._incOptions.copy(transactional = true)))
      .text("Restore previous class files on failure")

    opt[Unit]("no-zinc-file-manager")
      .abbr("no-zinc-file-manager")
      .action((x, c) =>
        c.copy(_incOptions = c._incOptions.copy(useZincFileManager = false)))
      .text("Disable zinc provided file manager")

    opt[File]("backup")
      .abbr("backup")
      .valueName("<directory>")
      .action((x, c) =>
        c.copy(_incOptions = c._incOptions.copy(backup = Some(x))))
      .text("Backup location (if transactional)")

    opt[File]("analysis-cache")
      .abbr("analysis-cache")
      .valueName("<file>")
      .action((x, c) => c.copy(analysis = c.analysis.copy(_cache = Some(x))))
      .text("Cache file to compile analysis")

    opt[Map[File, File]]("analysis-map")
      .abbr("analysis-map")
      .action((x, c) => c.copy(analysis = c.analysis.copy(cacheMap = x)))
      .text("Upstream analysis mapping (file=file,...)")

    opt[Map[File, File]]("rebase-map")
      .abbr("rebase-map")
      .action((x, c) => c.copy(analysis = c.analysis.copy(rebaseMap = x)))
      .text("Source and destination paths to rebase in persisted analysis (file=file,...)")

    opt[Unit]("no-clear-invalid-analysis")
      .abbr("no-clear-invalid-analysis")
      .action(
        (x, c) => c.copy(analysis = c.analysis.copy(clearInvalid = false)))
      .text("If set, zinc will fail rather than purging illegal analysis.")

    opt[String]("scalac-option")
      .abbr("S")
      .valueName("<scalac-option>")
      .unbounded()
      .action((x, c) => c.copy(scalacOptions = c.scalacOptions :+ x))
      .text("Pass option to scalac")

    opt[String]("javac-option")
      .abbr("C")
      .valueName("<javac-option>")
      .unbounded()
      .action((x, c) => c.copy(javacOptions = c.javacOptions :+ x))
      .text("Pass option to javac")

    arg[File]("<file>...")
      .unbounded()
      .action((x, c) => c.copy(_sources = c._sources :+ x))
      .text("Sources to compile")
  }

  /**
    * Create a CompileOrder value based on string input.
    */
  def compileOrder(order: String): CompileOrder = {
    order.toLowerCase match {
      case "mixed" => CompileOrder.Mixed
      case "java" | "java-then-scala" | "javathenscala" =>
        CompileOrder.JavaThenScala
      case "scala" | "scala-then-java" | "scalathenjava" =>
        CompileOrder.ScalaThenJava
    }
  }

  /**
    * Normalise all relative paths to absolute paths.
    */
  def normalise(f: File): File = f.getAbsoluteFile

  /**
    * By default the cache location is relative to the classes directory (for example, target/classes/../cache/classes).
    */
  def defaultCacheLocation(classesDir: File) = {
    classesDir.getParentFile / "cache" / classesDir.getName
  }

  /**
    * By default the backup location is relative to the classes directory (for example, target/classes/../backup/classes).
    */
  def defaultBackupLocation(classesDir: File): File = {
    classesDir.getParentFile / "backup" / classesDir.getName
  }

  /**
    * If a settings.classesDirectory option isnt specified, create a temporary directory for output
    * classes to be written to.
    */
  def defaultClassesDirectory(): File = {
    Files.createTempDirectory("temp-zinc-classes").toFile
  }
}
