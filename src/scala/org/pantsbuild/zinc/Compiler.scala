/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import java.net.URLClassLoader
import sbt.{ ClasspathOptions, CompileOptions, CompileSetup, LoggerReporter, ScalaInstance }
import sbt.compiler.{ AggressiveCompile, AnalyzingCompiler, CompilerCache, CompileOutput, IC }
import sbt.inc.{ Analysis, AnalysisStore, FileBasedStore }
import sbt.Path._
import xsbti.compile.{ JavaCompiler, GlobalsCache }
import xsbti.Logger

import org.pantsbuild.zinc.Cache.Implicits

object Compiler {
  val CompilerInterfaceId = "compiler-interface"
  val JavaClassVersion = System.getProperty("java.class.version")

  /**
   * Static cache for zinc compilers.
   */
  val compilerCache = Cache[Setup, Compiler](Setup.Defaults.compilerCacheLimit)

  /**
   * Static cache for resident scala compilers.
   */
  val residentCache: GlobalsCache = createResidentCache(Setup.Defaults.residentCacheLimit)

  /**
   * Static cache for compile analyses.  Values must be Options because in get() we don't yet know if, on
   * a cache miss, the underlying file will yield a valid Analysis.
   */
  val analysisCache = Cache[FileFPrint, Option[(Analysis, CompileSetup)]](Setup.Defaults.analysisCacheLimit)

  /**
   * Get or create a zinc compiler based on compiler setup.
   */
  def apply(setup: Setup, log: Logger): Compiler =
    compilerCache.getOrElseUpdate(setup) {
      create(setup, log)
    }

  /**
   * Java API for creating compiler.
   */
  def getOrCreate(setup: Setup, log: Logger): Compiler = apply(setup, log)

  /**
   * Create a new zinc compiler based on compiler setup.
   */
  def create(setup: Setup, log: Logger): Compiler = {
    val instance     = scalaInstance(setup)
    val interfaceJar = compilerInterface(setup, instance, log)
    val scalac       = newScalaCompiler(instance, interfaceJar, log)
    val javac        = newJavaCompiler(instance, setup.javaHome, setup.forkJava)
    new Compiler(scalac, javac, setup)
  }

  /**
   * Create a new scala compiler.
   */
  def newScalaCompiler(instance: ScalaInstance, interfaceJar: File, log: Logger): AnalyzingCompiler = {
    IC.newScalaCompiler(instance, interfaceJar, ClasspathOptions.boot, log)
  }

  /**

   */
  def newJavaCompiler(instance: ScalaInstance, javaHome: Option[File], fork: Boolean): JavaCompiler = {
    val options = ClasspathOptions.javac(false)
    if (fork || javaHome.isDefined)
      sbt.compiler.JavaCompiler.fork(options, instance)(AggressiveCompile.forkJavac(javaHome))
    else
      sbt.compiler.JavaCompiler.directOrFork(options, instance)(AggressiveCompile.forkJavac(None))
  }

  /**
   * Create new globals cache.
   */
  def createResidentCache(maxCompilers: Int): GlobalsCache = {
    if (maxCompilers <= 0) CompilerCache.fresh else CompilerCache(maxCompilers)
  }

  /**
   * Create an analysis store backed by analysisCache.
   */
  def analysisStore(cacheFile: File): AnalysisStore = {
    val fileStore = AnalysisStore.cached(FileBasedStore(cacheFile))

    val fprintStore = new AnalysisStore {
      def set(analysis: Analysis, setup: CompileSetup) {
        fileStore.set(analysis, setup)
        FileFPrint.fprint(cacheFile) foreach { analysisCache.put(_, Some((analysis, setup))) }
      }
      def get(): Option[(Analysis, CompileSetup)] = {
        FileFPrint.fprint(cacheFile) flatMap { fprint =>
          analysisCache.getOrElseUpdate(fprint) {
            fileStore.get
          }
        }
      }
    }

    AnalysisStore.sync(AnalysisStore.cached(fprintStore))
  }

  /**
   * Analysis for the given file if it is already cached.
   */
  def analysisOption(cacheFile: File): Option[Analysis] =
    analysisStore(cacheFile).get map (_._1)

  /**
   * Analysis for the given file, or Analysis.Empty if it is not in the cache.
   */
  def analysis(cacheFile: File): Analysis =
    analysisOption(cacheFile) getOrElse Analysis.Empty

  /**
   * Check whether an analysis is empty.
   */
  def analysisIsEmpty(cacheFile: File): Boolean = {
    analysis(cacheFile) eq Analysis.Empty
  }

  /**
   * Create the scala instance for the compiler. Includes creating the classloader.
   */
  def scalaInstance(setup: Setup): ScalaInstance = {
    import setup.{ scalaCompiler, scalaLibrary, scalaExtra}
    val loader = scalaLoader(scalaLibrary +: scalaCompiler +: scalaExtra)
    val version = scalaVersion(loader)
    new ScalaInstance(version.getOrElse("unknown"), loader, scalaLibrary, scalaCompiler, scalaExtra, version)
  }

  /**
   * Create a new classloader with the root loader as parent (to avoid zinc itself being included).
   */
  def scalaLoader(jars: Seq[File]) = new URLClassLoader(toURLs(jars), sbt.classpath.ClasspathUtilities.rootLoader)

  /**
   * Get the actual scala version from the compiler.properties in a classloader.
   * The classloader should only contain one version of scala.
   */
  def scalaVersion(scalaLoader: ClassLoader): Option[String] = {
    Util.propertyFromResource("compiler.properties", "version.number", scalaLoader)
  }

  /**
   * Get the compiler interface for this compiler setup. Compile it if not already cached.
   */
  def compilerInterface(setup: Setup, scalaInstance: ScalaInstance, log: Logger): File = {
    val dir = setup.cacheDir / interfaceId(scalaInstance.actualVersion)
    val interfaceJar = dir / (CompilerInterfaceId + ".jar")
    if (!interfaceJar.exists) {
      dir.mkdirs()
      IC.compileInterfaceJar(CompilerInterfaceId, setup.compilerInterfaceSrc, interfaceJar, setup.sbtInterface, scalaInstance, log)
    }
    interfaceJar
  }

  def interfaceId(scalaVersion: String) = CompilerInterfaceId + "-" + scalaVersion + "-" + JavaClassVersion
}

/**
 * A zinc compiler for incremental recompilation.
 */
class Compiler(scalac: AnalyzingCompiler, javac: JavaCompiler, setup: Setup) {

  /**
   * Run a compile. The resulting analysis is also cached in memory.
   *  Note:  This variant automatically contructs an error-reporter.
   */
  def compile(inputs: Inputs)(log: Logger): Analysis = compile(inputs, None)(log)

  /**
   * Run a compile. The resulting analysis is also cached in memory.
   *
   *  Note:  This variant automatically contructs an error-reporter.
   */
  def compile(inputs: Inputs, cwd: Option[File])(log: Logger): Analysis = {
    val maxErrors     = 100
    compile(inputs, cwd, new LoggerReporter(maxErrors, log, identity))(log)
  }

  /**
   * Run a compile. The resulting analysis is also cached in memory.
   * 
   *  Note: This variant does not report progress updates
   */
  def compile(inputs: Inputs, cwd: Option[File], reporter: xsbti.Reporter)(log: Logger): Analysis = {
    val progress = Some(new SimpleCompileProgress(setup.logPhases, setup.printDots)(log))
    compile(inputs, cwd, reporter, progress)(log)
  }

  /**
   * Run a compile. The resulting analysis is also cached in memory.
   */
  def compile(inputs: Inputs, cwd: Option[File], reporter: xsbti.Reporter, progress: Option[xsbti.compile.CompileProgress])(log: Logger): Analysis = {
    import inputs._
    if (forceClean && Compiler.analysisIsEmpty(cacheFile)) Util.cleanAllClasses(classesDirectory)
    val getAnalysis: File => Option[Analysis] = analysisMap.get _
    val aggressive    = new AggressiveCompile(cacheFile)
    val cp            = autoClasspath(classesDirectory, scalac.scalaInstance.allJars, javaOnly, classpath)
    val compileOutput = CompileOutput(classesDirectory)
    val globalsCache  = Compiler.residentCache
    val skip          = false
    val incOpts       = incOptions.options
    val compileSetup  = new CompileSetup(compileOutput, new CompileOptions(scalacOptions, javacOptions), scalac.scalaInstance.actualVersion, compileOrder, incOpts.nameHashing)
    val analysisStore = Compiler.analysisStore(cacheFile)
    val analysis      = aggressive.compile1(sources, cp, compileSetup, progress, analysisStore, getAnalysis, definesClass, scalac, javac, reporter, skip, globalsCache, incOpts)(log)
    if (mirrorAnalysis) {
      SbtAnalysis.printRelations(analysis, Some(new File(cacheFile.getPath() + ".relations")), cwd)
    }
    SbtAnalysis.printOutputs(analysis, outputRelations, outputProducts, cwd, classesDirectory)
    analysis
  }

  /**
   * Automatically add the output directory and scala library to the classpath.
   */
  def autoClasspath(classesDirectory: File, allScalaJars: Seq[File], javaOnly: Boolean, classpath: Seq[File]): Seq[File] = {
    if (javaOnly) classesDirectory +: classpath
    else Setup.splitScala(allScalaJars) match {
      case Some(scalaJars) => classesDirectory +: scalaJars.library +: classpath
      case None            => classesDirectory +: classpath
    }
  }

  override def toString = "Compiler(Scala %s)" format scalac.scalaInstance.actualVersion
}
