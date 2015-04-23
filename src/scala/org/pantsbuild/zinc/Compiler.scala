/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import java.net.URLClassLoader

import sbt.Path._
import sbt.compiler.{AggressiveCompile, AnalyzingCompiler, CompileOutput, CompilerCache, IC}
import sbt.inc.{Analysis, AnalysisStore, FileBasedStore}
import sbt.{ClasspathOptions, CompileOptions, CompileSetup, LoggerReporter, ScalaInstance}
import xsbti.Logger
import xsbti.compile.{GlobalsCache, JavaCompiler}

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
   * Java API for creating compiler.
   */
  def getOrCreate(setup: Setup, log: Logger): Compiler = apply(setup, log)
  /**
   * Get or create a zinc compiler based on compiler setup.
   */
  def apply(setup: Setup, log: Logger): Compiler = {
    compilerCache.get(setup)(create(setup, log))
  }
  /**
   * Create a new zinc compiler based on compiler setup.
   */
  def create(setup: Setup, log: Logger): Compiler = {
    val instance = scalaInstance(setup)
    val interfaceJar = compilerInterface(setup, instance, log)
    val scalac = newScalaCompiler(instance, interfaceJar, log)
    val javac = newJavaCompiler(instance, setup.javaHome, setup.forkJava)
    new Compiler(scalac, javac)
  }

  /**
   * Create a new scala compiler.
   */
  def newScalaCompiler(instance: ScalaInstance, interfaceJar: File, log: Logger): AnalyzingCompiler = {
    IC.newScalaCompiler(instance, interfaceJar, ClasspathOptions.boot, log)
  }

  /**
   * Create a new java compiler.
   */
  def newJavaCompiler(instance: ScalaInstance, javaHome: Option[File], fork: Boolean): JavaCompiler = {
    val options = ClasspathOptions.javac(false)
    if (fork || javaHome.isDefined)
      sbt.compiler.JavaCompiler.fork(options, instance)(AggressiveCompile.forkJavac(javaHome))
    else
      sbt.compiler.JavaCompiler.directOrFork(options, instance)(AggressiveCompile.forkJavac(None))
  }
  /**
   * Create the scala instance for the compiler. Includes creating the classloader.
   */
  def scalaInstance(setup: Setup): ScalaInstance = {
    val loader = scalaLoader(setup.scalaLibrary +: setup.scalaCompiler +: setup.scalaExtra)
    val version = scalaVersion(loader)
    new ScalaInstance(version.getOrElse("unknown"), loader, setup.scalaLibrary, setup.scalaCompiler,
      setup.scalaExtra, version)
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
  /**
   * Create new globals cache.
   */
  def createResidentCache(maxCompilers: Int): GlobalsCache = {
    if (maxCompilers <= 0) CompilerCache.fresh else CompilerCache(maxCompilers)
  }
  /**
   * Check whether an analysis is empty.
   */
  def analysisIsEmpty(cacheFile: File): Boolean = {
    analysis(cacheFile) eq Analysis.Empty
  }
  /**
   * Get an analysis, lookup by cache file.
   */
  def analysis(cacheFile: File): Analysis = {
    analysisStore(cacheFile).get map (_._1) getOrElse Analysis.Empty
  }
  /**
   * Create an analysis store backed by analysisCache.
   */
  def analysisStore(cacheFile: File): AnalysisStore = {
    val fileStore = AnalysisStore.cached(FileBasedStore(cacheFile))

    val fprintStore = new AnalysisStore {
      def set(analysis: Analysis, setup: CompileSetup) {
        fileStore.set(analysis, setup)
        FileFPrint.fprint(cacheFile) foreach {
          analysisCache.put(_, Some((analysis, setup)))
        }
      }
      def get(): Option[(Analysis, CompileSetup)] = {
        FileFPrint.fprint(cacheFile) flatMap { fprint => analysisCache.get(fprint)(fileStore.get) }
      }
    }

    AnalysisStore.sync(AnalysisStore.cached(fprintStore))
  }
}

/**
 * A zinc compiler for incremental recompilation.
 */
class Compiler(scalac: AnalyzingCompiler, javac: JavaCompiler) {

  /**
   * Run a compile. The resulting analysis is also cached in memory.
   * Note:  This variant automatically contructs an error-reporter.
   */
  def compile(inputs: Inputs)(log: Logger): Analysis = compile(inputs, None)(log)

  /**
   * Run a compile. The resulting analysis is also cached in memory.
   *
   * Note:  This variant automatically contructs an error-reporter.
   */
  def compile(inputs: Inputs, cwd: Option[File])(log: Logger): Analysis = {
    val maxErrors = 100
    compile(inputs, cwd, new LoggerReporter(maxErrors, log, identity))(log)
  }

  /**
   * Run a compile. The resulting analysis is also cached in memory.
   *
   * Note: This variant does not report progress updates
   */
  def compile(inputs: Inputs, cwd: Option[File], reporter: xsbti.Reporter)(log: Logger): Analysis = {
    compile(inputs, cwd, reporter, progress = None)(log)
  }

  /**
   * Run a compile. The resulting analysis is also cached in memory.
   */
  def compile(inputs: Inputs, cwd: Option[File], reporter: xsbti.Reporter,
      progress: Option[xsbti.compile.CompileProgress])(log: Logger): Analysis = {
    if (inputs.forceClean && Compiler.analysisIsEmpty(inputs.cacheFile))
      Util.cleanAllClasses(inputs.classesDirectory)
    val getAnalysis: File => Option[Analysis] = inputs.analysisMap.get _
    val aggressive = new AggressiveCompile(inputs.cacheFile)
    val cp = autoClasspath(inputs.classesDirectory, scalac.scalaInstance.allJars,
      inputs.javaOnly, inputs.classpath)
    val compileOutput = CompileOutput(inputs.classesDirectory)
    val globalsCache = Compiler.residentCache
    val skip = false
    val incOpts = inputs.incOptions.options
    val compileSetup = new CompileSetup(compileOutput,
      new CompileOptions(inputs.scalacOptions, inputs.javacOptions),
      scalac.scalaInstance.actualVersion, inputs.compileOrder, incOpts.nameHashing)
    val analysisStore = Compiler.analysisStore(inputs.cacheFile)
    val analysis = aggressive.compile1(inputs.sources, cp, compileSetup, progress, analysisStore,
      getAnalysis, inputs.definesClass, scalac, javac, reporter, skip, globalsCache, incOpts)(log)
    if (inputs.mirrorAnalysis) {
      SbtAnalysis.printRelations(analysis,
        Some(new File(inputs.cacheFile.getPath() + ".relations")), cwd)
    }
    SbtAnalysis.printOutputs(analysis, inputs.outputRelations, inputs.outputProducts, cwd,
      inputs.classesDirectory)
    analysis
  }

  /**
   * Automatically add the output directory and scala library to the classpath.
   */
  def autoClasspath(classesDirectory: File, allScalaJars: Seq[File], javaOnly: Boolean,
      classpath: Seq[File]): Seq[File] = {
    if (javaOnly) classesDirectory +: classpath
    else Setup.splitScala(allScalaJars) match {
      case Some(scalaJars) => classesDirectory +: scalaJars.library +: classpath
      case None => classesDirectory +: classpath
    }
  }

  override def toString = "Compiler(Scala %s)" format scalac.scalaInstance.actualVersion
}
