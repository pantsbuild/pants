/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc.compiler

import java.io.File
import sbt.internal.util.{ ConsoleLogger, ConsoleOut }
import java.nio.file.{Files, Path}
import java.lang.{ Boolean => JBoolean }
import java.util.function.{ Function => JFunction }
import java.util.{ List => JList, logging => jlogging }

import scala.collection.JavaConverters._
import scala.compat.java8.OptionConverters._
import scala.util.matching.Regex

import sbt.io.Path._
import sbt.io.syntax._
import sbt.util.{Level, Logger}
import xsbti.compile.{
  ClassFileManagerType,
  CompileOrder,
  IncOptionsUtil,
  TransactionalManagerType
}
import xsbti.compile.{IncOptions => ZincIncOptions}

import org.pantsbuild.zinc.analysis.AnalysisOptions
import org.pantsbuild.zinc.options.OptionSet
import org.pantsbuild.zinc.util.Util

/**
 * All parsed command-line options.
 */
case class Settings(
  help: Boolean                     = false,
  version: Boolean                  = false,
  consoleLog: ConsoleOptions        = ConsoleOptions(),
  _sources: Seq[File]               = Seq.empty,
  classpath: Seq[File]              = Seq.empty,
  _classesDirectory: Option[File]   = None,
  outputJar: Option[File]           = None,
  scala: ScalaLocation              = ScalaLocation(),
  scalacOptions: Seq[String]        = Seq.empty,
  javaHome: Option[File]            = None,
  javaOnly: Boolean                 = false,
  javacOptions: Seq[String]         = Seq.empty,
  compileOrder: CompileOrder        = CompileOrder.Mixed,
  _incOptions: IncOptions           = IncOptions(),
  analysis: AnalysisOptions         = AnalysisOptions(),
  creationTime: Long                = 0,
  compiledBridgeJar: Option[File]= None
) {
  import Settings._

  lazy val sources: Seq[File] = _sources map normalise

  lazy val classesDirectory: File =
    normalise(_classesDirectory.getOrElse(defaultClassesDirectory()))

  lazy val incOptions: IncOptions = {
    _incOptions.copy(
      apiDumpDirectory = _incOptions.apiDumpDirectory map normalise,
      backup = {
        if (_incOptions.transactional)
          Some(normalise(_incOptions.backup.getOrElse(defaultBackupLocation(classesDirectory))))
        else
          None
      }
    )
  }

  def withAbsolutePaths(relativeTo: File): Settings = {
    def normaliseSeq(seq: Seq[File]): Seq[File] = Util.normaliseSeq(Some(relativeTo))(seq)
    def normaliseOpt(opt: Option[File]): Option[File] = Util.normaliseOpt(Some(relativeTo))(opt)

    // It's a shame that this is manually listing the args which are files, but this doesn't feel
    // high-value enough to fold into the full options parsing
    // (which we may delete at some point anyway)...
    this.copy(
      _sources = normaliseSeq(_sources),
      classpath = normaliseSeq(classpath),
      _classesDirectory = normaliseOpt(_classesDirectory),
      outputJar = normaliseOpt(outputJar),
      scala = scala.withAbsolutePaths(relativeTo),
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
  logLevel: Level.Value      = Level.Info,
  color: Boolean             = true,
  fileFilters: Seq[Regex]    = Seq.empty,
  msgFilters: Seq[Regex]     = Seq.empty
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
  home: Option[File]     = None,
  path: Seq[File]        = Seq.empty,
  compiler: Option[File] = None,
  library: Option[File]  = None,
  extra: Seq[File]       = Seq.empty
) {
  def withAbsolutePaths(relativeTo: File): ScalaLocation = {
    def normaliseSeq(seq: Seq[File]): Seq[File] = Util.normaliseSeq(Some(relativeTo))(seq)
    def normaliseOpt(opt: Option[File]): Option[File] = Util.normaliseOpt(Some(relativeTo))(opt)

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
  def create(
    home: File,
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
  transitiveStep: Int            = ZincIncOptions.defaultTransitiveStep,
  recompileAllFraction: Double   = ZincIncOptions.defaultRecompileAllFraction,
  relationsDebug: Boolean        = ZincIncOptions.defaultRelationsDebug,
  apiDebug: Boolean              = ZincIncOptions.defaultApiDebug,
  apiDiffContextSize: Int        = ZincIncOptions.defaultApiDiffContextSize,
  apiDumpDirectory: Option[File] = ZincIncOptions.defaultApiDumpDirectory.asScala,
  transactional: Boolean         = false,
  useZincFileManager: Boolean    = true,
  backup: Option[File]           = None
) {
  def options(log: Logger): ZincIncOptions =
    ZincIncOptions.create()
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

object Settings extends OptionSet[Settings] {
  val DestinationOpt = "-d"
  val JarDestinationOpt = "-jar"

  override def empty = Settings()

  override def applyResidual(t: Settings, residualArgs: Seq[String]) =
    t.copy(_sources = residualArgs map (new File(_)))

  override val options = Seq(
    header("Output options:"),
    boolean(  ("-help", "-h"),                 "Print this usage message",                   (s: Settings) => s.copy(help = true)),
    boolean(   "-version",                     "Print version",                              (s: Settings) => s.copy(version = true)),

    header("Logging Options:"),
    boolean(   "-debug",                       "Set log level for stdout to debug",
      (s: Settings) => s.copy(consoleLog = s.consoleLog.copy(logLevel = Level.Debug))),
    string(    "-log-level", "level",          "Set log level for stdout (debug|info|warn|error)",
      (s: Settings, l: String) => s.copy(consoleLog = s.consoleLog.copy(logLevel = Level.withName(l)))),
    boolean(   "-no-color",                    "No color in logging to stdout",
      (s: Settings) => s.copy(consoleLog = s.consoleLog.copy(color = false))),
    string(    "-msg-filter", "regex",         "Filter warning messages matching the given regex",
      (s: Settings, re: String) => s.copy(consoleLog = s.consoleLog.copy(msgFilters = s.consoleLog.msgFilters :+ re.r))),
    string(    "-file-filter", "regex",        "Filter warning messages from filenames matching the given regex",
      (s: Settings, re: String) => s.copy(consoleLog = s.consoleLog.copy(fileFilters = s.consoleLog.fileFilters :+ re.r))),

    header("Compile options:"),
    path(     ("-classpath", "-cp"), "path",   "Specify the classpath",                      (s: Settings, cp: Seq[File]) => s.copy(classpath = cp)),
    file(     DestinationOpt, "directory",     "Destination for compiled classes",           (s: Settings, f: File) => s.copy(_classesDirectory = Some(f))),
    file(     JarDestinationOpt, "directory",     "Jar destination for compiled classes",           (s: Settings, f: File) => s.copy(outputJar = Some(f))),
    long("-jar-creation-time", "n",        "Creation timestamp for compiled jars, default is current time", (s: Settings, l: Long) => s.copy(creationTime = l)),

    header("Scala options:"),
    file(      "-scala-home", "directory",     "Scala home directory (for locating jars)",   (s: Settings, f: File) => s.copy(scala = s.scala.copy(home = Some(f)))),
    path(      "-scala-path", "path",          "Specify all Scala jars directly",            (s: Settings, sp: Seq[File]) => s.copy(scala = s.scala.copy(path = sp))),
    file(      "-scala-compiler", "file",      "Specify Scala compiler jar directly" ,       (s: Settings, f: File) => s.copy(scala = s.scala.copy(compiler = Some(f)))),
    file(      "-scala-library", "file",       "Specify Scala library jar directly" ,        (s: Settings, f: File) => s.copy(scala = s.scala.copy(library = Some(f)))),
    path(      "-scala-extra", "path",         "Specify extra Scala jars directly",          (s: Settings, e: Seq[File]) => s.copy(scala = s.scala.copy(extra = e))),
    prefix(    "-S", "<scalac-option>",        "Pass option to scalac",                      (s: Settings, o: String) => s.copy(scalacOptions = s.scalacOptions :+ o)),

    header("Java options:"),
    file(      "-java-home", "directory",      "Select javac home directory (and fork)",     (s: Settings, f: File) => s.copy(javaHome = Some(f))),
    string(    "-compile-order", "order",      "Compile order for Scala and Java sources",   (s: Settings, o: String) => s.copy(compileOrder = compileOrder(o))),
    boolean(   "-java-only",                   "Don't add scala library to classpath",       (s: Settings) => s.copy(javaOnly = true)),
    prefix(    "-C", "<javac-option>",         "Pass option to javac",                       (s: Settings, o: String) => s.copy(javacOptions = s.javacOptions :+ o)),

    header("sbt options:"),
    file("-compiled-bridge-jar", "file", "Path to pre-compiled compiler interface", (s: Settings, f: File) => s.copy(compiledBridgeJar = Some(f))),

    header("Incremental compiler options:"),
    int(       "-transitive-step", "n",        "Steps before transitive closure",            (s: Settings, i: Int) => s.copy(_incOptions = s._incOptions.copy(transitiveStep = i))),
    fraction(  "-recompile-all-fraction", "x", "Limit before recompiling all sources",       (s: Settings, d: Double) => s.copy(_incOptions = s._incOptions.copy(recompileAllFraction = d))),
    boolean(   "-debug-relations",             "Enable debug logging of analysis relations", (s: Settings) => s.copy(_incOptions = s._incOptions.copy(relationsDebug = true))),
    boolean(   "-debug-api",                   "Enable analysis API debugging",              (s: Settings) => s.copy(_incOptions = s._incOptions.copy(apiDebug = true))),
    file(      "-api-dump", "directory",       "Destination for analysis API dump",          (s: Settings, f: File) => s.copy(_incOptions = s._incOptions.copy(apiDumpDirectory = Some(f)))),
    int(       "-api-diff-context-size", "n",  "Diff context size (in lines) for API debug", (s: Settings, i: Int) => s.copy(_incOptions = s._incOptions.copy(apiDiffContextSize = i))),
    boolean(   "-transactional",               "Restore previous class files on failure",    (s: Settings) => s.copy(_incOptions = s._incOptions.copy(transactional = true))),
    boolean(   "-no-zinc-file-manager",        "Disable zinc provided file manager",           (s: Settings) => s.copy(_incOptions = s._incOptions.copy(useZincFileManager = false))),
    file(      "-backup", "directory",         "Backup location (if transactional)",         (s: Settings, f: File) => s.copy(_incOptions = s._incOptions.copy(backup = Some(f)))),

    header("Analysis options:"),
    file(      "-analysis-cache", "file",      "Cache file for compile analysis",            (s: Settings, f: File) => s.copy(analysis =
      s.analysis.copy(_cache = Some(f)))),
    fileMap(   "-analysis-map",                "Upstream analysis mapping (file:file,...)",
      (s: Settings, m: Map[File, File]) => s.copy(analysis = s.analysis.copy(cacheMap = m))),
    fileMap(   "-rebase-map",                  "Source and destination paths to rebase in persisted analysis (file:file,...)",
      (s: Settings, m: Map[File, File]) => s.copy(analysis = s.analysis.copy(rebaseMap = m))),
    boolean(   "-no-clear-invalid-analysis",   "If set, zinc will fail rather than purging illegal analysis.",
      (s: Settings) => s.copy(analysis = s.analysis.copy(clearInvalid = false)))
  )

  /**
   * Create a CompileOrder value based on string input.
   */
  def compileOrder(order: String): CompileOrder = {
    order.toLowerCase match {
      case "mixed"                                       => CompileOrder.Mixed
      case "java"  | "java-then-scala" | "javathenscala" => CompileOrder.JavaThenScala
      case "scala" | "scala-then-java" | "scalathenjava" => CompileOrder.ScalaThenJava
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
