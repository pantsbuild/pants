/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import java.util.{ List => JList }

import scala.collection.JavaConverters._
import scala.compat.java8.OptionConverters._
import scala.util.matching.Regex

import sbt.io.Path._
import sbt.io.syntax._
import sbt.util.{Level, Logger}
import xsbti.Maybe
import xsbti.compile.{
  ClassFileManagerType,
  CompileOrder,
  TransactionalManagerType
}
import xsbti.compile.IncOptionsUtil.defaultIncOptions


/**
 * All parsed command-line options.
 */
case class Settings(
  help: Boolean              = false,
  version: Boolean           = false,
  consoleLog: ConsoleOptions = ConsoleOptions(),
  _sources: Seq[File]         = Seq.empty,
  _classpath: Seq[File]       = Seq.empty,
  _classesDirectory: File     = new File("."),
  scala: ScalaLocation       = ScalaLocation(),
  scalacOptions: Seq[String] = Seq.empty,
  javaHome: Option[File]     = None,
  forkJava: Boolean          = false,
  _zincCacheDir: Option[File] = None,
  javaOnly: Boolean          = false,
  javacOptions: Seq[String]  = Seq.empty,
  compileOrder: CompileOrder = CompileOrder.Mixed,
  sbt: SbtJars               = SbtJars(),
  _incOptions: IncOptions     = IncOptions(),
  analysis: AnalysisOptions  = AnalysisOptions()
) {
  import Settings._

  lazy val zincCacheDir: File = _zincCacheDir.getOrElse {
    throw new RuntimeException(s"The ${Settings.ZincCacheDirOpt} option is required.")
  }

  lazy val classpath: Seq[File] = _classpath map normalise

  lazy val sources: Seq[File] = _sources map normalise

  lazy val classesDirectory: File = normalise(_classesDirectory)

  lazy val cacheFile: File = {
    normalise(analysis._cache.getOrElse(defaultCacheLocation(classesDirectory)))
  }

  lazy val cacheMap: Map[File, File] =
    analysis._cacheMap.collect {
      case (k, v) if normalise(k) != classesDirectory =>
        (normalise(k), normalise(v))
    }

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
}

/** Due to the limit of 22 elements in a case class, options must get broken down into sub-groups.
 * TODO: further break options into sensible subgroups. */
case class ConsoleOptions(
  logLevel: Level.Value      = Level.Info,
  color: Boolean             = true,
  logPhases: Boolean         = false,
  printProgress: Boolean     = false,
  heartbeatSecs: Int         = 0,
  fileFilters: Seq[Regex]    = Seq.empty,
  msgFilters: Seq[Regex]     = Seq.empty
)

/**
 * Alternative ways to locate the scala jars.
 */
case class ScalaLocation(
  home: Option[File]     = None,
  path: Seq[File]        = Seq.empty,
  compiler: Option[File] = None,
  library: Option[File]  = None,
  extra: Seq[File]       = Seq.empty
)

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
 * Locating the sbt jars needed for zinc compile.
 */
case class SbtJars(
  compilerBridgeSrc: Option[File] = None,
  compilerInterface: Option[File] = None
) {
  lazy val jars: (File, File) = (compilerBridgeSrc, compilerInterface) match {
    case (Some(x), Some(y)) if x.exists && y.exists => (x, y)
    case (Some(x), Some(y)) =>
      throw new RuntimeException(s"One or both of $x and $y do not exist.")
    case _ =>
      throw new RuntimeException(
        s"Both the ${Settings.CompilerBridgeOpt} and " +
        s"${Settings.CompilerInterfaceOpt} options are required."
      )
  }
}

/**
 * Wrapper around incremental compiler options.
 */
case class IncOptions(
  transitiveStep: Int            = defaultIncOptions.transitiveStep,
  recompileAllFraction: Double   = defaultIncOptions.recompileAllFraction,
  relationsDebug: Boolean        = defaultIncOptions.relationsDebug,
  apiDebug: Boolean              = defaultIncOptions.apiDebug,
  apiDiffContextSize: Int        = defaultIncOptions.apiDiffContextSize,
  apiDumpDirectory: Option[File] = defaultIncOptions.apiDumpDirectory.asScala,
  transactional: Boolean         = false,
  useZincFileManager: Boolean    = true,
  backup: Option[File]           = None,
  recompileOnMacroDef: Option[Boolean] =
    defaultIncOptions.recompileOnMacroDef.asScala.map(_.booleanValue)
) {
  def options(log: Logger): xsbti.compile.IncOptions = {
    new xsbti.compile.IncOptions(
      transitiveStep,
      recompileAllFraction,
      relationsDebug,
      apiDebug,
      apiDiffContextSize,
      apiDumpDirectory.asJava,
      classfileManager(log).asJava,
      useZincFileManager,
      recompileOnMacroDef.map(java.lang.Boolean.valueOf).asJava,
      true, // nameHashing
      false, // storeApis, apis is stored separately after 1.0.0
      false, // antStyle
      Map.empty.asJava, // extra
      defaultIncOptions.logRecompileOnMacro,
      defaultIncOptions.externalHooks
    )
  }

  def defaultApiDumpDirectory =
    defaultIncOptions.apiDumpDirectory

  def classfileManager(log: Logger): Option[ClassFileManagerType] =
    if (transactional && backup.isDefined)
      Some(new TransactionalManagerType(backup.get, log))
    else
      None
}

/**
 * Configuration for sbt analysis and analysis output options.
 */
case class AnalysisOptions(
  _cache: Option[File]           = None,
  _cacheMap: Map[File, File]     = Map.empty
)

object Settings {
  val ZincCacheDirOpt = "-zinc-cache-dir"
  val CompilerBridgeOpt = "-compiler-bridge"
  val CompilerInterfaceOpt = "-compiler-interface"

  /**
   * All available command-line options.
   */
  val options = Seq(
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
    boolean(   "-log-phases",                  "Log phases of compilation for each file to stdout",
      (s: Settings) => s.copy(consoleLog = s.consoleLog.copy(logPhases = true))),
    boolean(   "-print-progress",              "Periodically print compilation progress to stdout",
      (s: Settings) => s.copy(consoleLog = s.consoleLog.copy(printProgress = true))),
    int(       "-heartbeat", "interval (sec)", "Print '.' to stdout every n seconds while compiling",
      (s: Settings, b: Int) => s.copy(consoleLog = s.consoleLog.copy(heartbeatSecs = b))),
    string(    "-msg-filter", "regex",         "Filter warning messages matching the given regex",
      (s: Settings, re: String) => s.copy(consoleLog = s.consoleLog.copy(msgFilters = s.consoleLog.msgFilters :+ re.r))),
    string(    "-file-filter", "regex",        "Filter warning messages from filenames matching the given regex",
      (s: Settings, re: String) => s.copy(consoleLog = s.consoleLog.copy(fileFilters = s.consoleLog.fileFilters :+ re.r))),

    header("Compile options:"),
    path(     ("-classpath", "-cp"), "path",   "Specify the classpath",                      (s: Settings, cp: Seq[File]) => s.copy(_classpath = cp)),
    file(      "-d", "directory",              "Destination for compiled classes",           (s: Settings, f: File) => s.copy(_classesDirectory = f)),

    header("Scala options:"),
    file(      "-scala-home", "directory",     "Scala home directory (for locating jars)",   (s: Settings, f: File) => s.copy(scala = s.scala.copy(home = Some(f)))),
    path(      "-scala-path", "path",          "Specify all Scala jars directly",            (s: Settings, sp: Seq[File]) => s.copy(scala = s.scala.copy(path = sp))),
    file(      "-scala-compiler", "file",      "Specify Scala compiler jar directly" ,       (s: Settings, f: File) => s.copy(scala = s.scala.copy(compiler = Some(f)))),
    file(      "-scala-library", "file",       "Specify Scala library jar directly" ,        (s: Settings, f: File) => s.copy(scala = s.scala.copy(library = Some(f)))),
    path(      "-scala-extra", "path",         "Specify extra Scala jars directly",          (s: Settings, e: Seq[File]) => s.copy(scala = s.scala.copy(extra = e))),
    prefix(    "-S", "<scalac-option>",        "Pass option to scalac",                      (s: Settings, o: String) => s.copy(scalacOptions = s.scalacOptions :+ o)),

    header("Java options:"),
    file(      "-java-home", "directory",      "Select javac home directory (and fork)",     (s: Settings, f: File) => s.copy(javaHome = Some(f))),
    boolean(   "-fork-java",                   "Run java compiler in separate process",      (s: Settings) => s.copy(forkJava = true)),
    string(    "-compile-order", "order",      "Compile order for Scala and Java sources",   (s: Settings, o: String) => s.copy(compileOrder = compileOrder(o))),
    boolean(   "-java-only",                   "Don't add scala library to classpath",       (s: Settings) => s.copy(javaOnly = true)),
    prefix(    "-C", "<javac-option>",         "Pass option to javac",                       (s: Settings, o: String) => s.copy(javacOptions = s.javacOptions :+ o)),

    header("sbt options:"),
    file(      CompilerBridgeOpt, "file",     "Specify compiler bridge sources jar",        (s: Settings, f: File) => s.copy(sbt = s.sbt.copy(compilerBridgeSrc = Some(f)))),
    file(      CompilerInterfaceOpt, "file",  "Specify compiler interface jar",             (s: Settings, f: File) => s.copy(sbt = s.sbt.copy(compilerInterface = Some(f)))),
    file(      ZincCacheDirOpt, "file",       "A cache directory for compiler interfaces",  (s: Settings, f: File) => s.copy(_zincCacheDir = Some(f))),

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
    boolean(   "-recompileOnMacroDefDisabled", "Disable recompilation of all dependencies of a macro def",
      (s: Settings) => s.copy(_incOptions = s._incOptions.copy(recompileOnMacroDef = Some(false)))),

    header("Analysis options:"),
    file(      "-analysis-cache", "file",      "Cache file for compile analysis",            (s: Settings, f: File) => s.copy(analysis =
      s.analysis.copy(_cache = Some(f)))),
    fileMap(   "-analysis-map",                "Upstream analysis mapping (file:file,...)",
      (s: Settings, m: Map[File, File]) => s.copy(analysis = s.analysis.copy(_cacheMap = m)))
  )

  val allOptions: Set[OptionDef[Settings]] = options.toSet

  /**
   * Print out the usage message.
   */
  def printUsage(cmdName: String): Unit = {
    val column = options.map(_.length).max + 2
    println(s"Usage: ${cmdName} <options> <sources>")
    options foreach { opt => if (opt.extraline) println(); println(opt.usage(column)) }
    println()
  }

  /**
   * The string name for system property with the given name suffix (prefixed with `zinc.`).
   */
  def prop(name: String) = s"zinc.${name}"

  /**
   * Anything starting with '-' is considered an option, not a source file.
   */
  def isOpt(s: String) = s startsWith "-"

  /**
   * Parse all args into a Settings object.
   * Residual args are either unknown options or source files.
   */
  def parse(args: Seq[String]): Parsed[Settings] = {
    val Parsed(settings, remaining, errors) = Options.parse(Settings(), allOptions, args, stopOnError = false)
    val (unknown, residual) = remaining partition isOpt
    val sources = residual map (new File(_))
    val unknownErrors = unknown map ("Unknown option: " + _)
    Parsed(settings.copy(_sources = sources), Seq.empty, errors ++ unknownErrors)
  }

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
   * Normalise all relative paths to the actual current working directory, if provided.
   * TODO: Actually necessary? If so, then the other absolute normalization is not
   * necessary.
   */
  def normaliseRelative(settings: Settings, cwd: Option[File]): Settings = {
    if (cwd.isEmpty) settings
    else {
      import settings._
      settings.copy(
        _sources = Util.normaliseSeq(cwd)(_sources),
        _classpath = Util.normaliseSeq(cwd)(_classpath),
        _classesDirectory = Util.normalise(cwd)(_classesDirectory),
        scala = scala.copy(
          home = Util.normaliseOpt(cwd)(scala.home),
          path = Util.normaliseSeq(cwd)(scala.path),
          compiler = Util.normaliseOpt(cwd)(scala.compiler),
          library = Util.normaliseOpt(cwd)(scala.library),
          extra = Util.normaliseSeq(cwd)(scala.extra)
        ),
        javaHome = Util.normaliseOpt(cwd)(javaHome),
        sbt = sbt.copy(
          compilerBridgeSrc = Util.normaliseOpt(cwd)(sbt.compilerBridgeSrc),
          compilerInterface = Util.normaliseOpt(cwd)(sbt.compilerInterface)
        ),
        _incOptions = _incOptions.copy(
          apiDumpDirectory = Util.normaliseOpt(cwd)(incOptions.apiDumpDirectory),
          backup = Util.normaliseOpt(cwd)(incOptions.backup)
        ),
        analysis = analysis.copy(
          _cache = Util.normaliseOpt(cwd)(analysis._cache),
          _cacheMap = Util.normaliseMap(cwd)(analysis._cacheMap)
        )
      )
    }
  }

  /**
   * By default the cache location is relative to the classes directory (for example, target/classes/../cache/classes).
   */
  def defaultCacheLocation(classesDir: File) = {
    classesDir.getParentFile / "cache" / classesDir.getName
  }

  /**
   * By default the backup location is relative to the classes directory (for example, target/classes/../backup/classes).
   */
  def defaultBackupLocation(classesDir: File) = {
    classesDir.getParentFile / "backup" / classesDir.getName
  }

  // NB: These cannot be options, because they are consumed statically.
  val cacheLimit         = Util.intProperty(prop("cache.limit"), 5)
  val analysisCacheLimit = Util.intProperty(prop("analysis.cache.limit"), cacheLimit)
  val compilerCacheLimit = Util.intProperty(prop("compiler.cache.limit"), cacheLimit)
  val residentCacheLimit = Util.intProperty(prop("resident.cache.limit"), 0)

  // helpers for creating options

  def boolean(opt: String, desc: String, action: Settings => Settings) = new BooleanOption[Settings](Seq(opt), desc, action)
  def boolean(opts: (String, String), desc: String, action: Settings => Settings) = new BooleanOption[Settings](Seq(opts._1, opts._2), desc, action)
  def string(opt: String, arg: String, desc: String, action: (Settings, String) => Settings) = new StringOption[Settings](Seq(opt), arg, desc, action)
  def int(opt: String, arg: String, desc: String, action: (Settings, Int) => Settings) = new IntOption[Settings](Seq(opt), arg, desc, action)
  def double(opt: String, arg: String, desc: String, action: (Settings, Double) => Settings) = new DoubleOption[Settings](Seq(opt), arg, desc, action)
  def fraction(opt: String, arg: String, desc: String, action: (Settings, Double) => Settings) = new FractionOption[Settings](Seq(opt), arg, desc, action)
  def file(opt: String, arg: String, desc: String, action: (Settings, File) => Settings) = new FileOption[Settings](Seq(opt), arg, desc, action)
  def path(opt: String, arg: String, desc: String, action: (Settings, Seq[File]) => Settings) = new PathOption[Settings](Seq(opt), arg, desc, action)
  def path(opts: (String, String), arg: String, desc: String, action: (Settings, Seq[File]) => Settings) = new PathOption[Settings](Seq(opts._1, opts._2), arg, desc, action)
  def prefix(pre: String, arg: String, desc: String, action: (Settings, String) => Settings) = new PrefixOption[Settings](pre, arg, desc, action)
  def filePair(opt: String, arg: String, desc: String, action: (Settings, (File, File)) => Settings) = new FilePairOption[Settings](Seq(opt), arg, desc, action)
  def fileMap(opt: String, desc: String, action: (Settings, Map[File, File]) => Settings) = new FileMapOption[Settings](Seq(opt), desc, action)
  def fileSeqMap(opt: String, desc: String, action: (Settings, Map[Seq[File], File]) => Settings) = new FileSeqMapOption[Settings](Seq(opt), desc, action)
  def header(label: String) = new HeaderOption[Settings](label)
  def dummy(opt: String, desc: String) = new DummyOption[Settings](opt, desc)
}
