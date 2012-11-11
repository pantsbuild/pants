/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package com.typesafe.zinc

import java.io.File
import sbt.{ CompileSetup, IO, Logger, Path, Relation }
import sbt.compiler.CompileOutput
import sbt.inc.{ APIs, Analysis, Relations, SourceInfos, Stamps }
import scala.annotation.tailrec
import xsbti.compile.SingleOutput

object SbtAnalysis {

  /**
   * Run analysis manipulation utilities.
   */
  def runUtil(util: AnalysisUtil, log: Logger): Unit = {
    runMerge(util.cache, util.merge)
    runRebase(util.cache, util.rebase)
    runSplit(util.cache, util.split)
    runReload(util.reload)
  }

  /**
   * Run an analysis merge. The given analyses should share the same compile setup.
   * The merged analysis will overwrite whatever is in the combined analysis cache.
   */
  def runMerge(combinedCache: Option[File], cacheFiles: Seq[File]): Unit = {
    if (cacheFiles.nonEmpty) {
      combinedCache match {
        case None => throw new Exception("No cache file specified")
        case Some(cacheFile) =>
          val analysisStore = Compiler.analysisStore(cacheFile)
          mergeAnalyses(cacheFiles) match {
            case Some((mergedAnalysis, mergedSetup)) => analysisStore.set(mergedAnalysis, mergedSetup)
            case None =>
          }
      }
    }
  }

  /**
   * Merge analyses and setups into one analysis and setup.
   * Currently the compile setups are not actually merged, last one wins.
   */
  def mergeAnalyses(cacheFiles: Seq[File]): Option[(Analysis, CompileSetup)] = {
    cacheFiles.foldLeft(None: Option[(Analysis, CompileSetup)]) { (merged, cacheFile) =>
      val store = Compiler.analysisStore(cacheFile)
      store.get match {
        case None => merged
        case merging @ Some((analysis, setup)) => merged map { case (a, _) => (a ++ analysis, setup) } orElse merging
      }
    }
  }

  /**
   * Run an analysis rebase. Rebase all paths in the analysis, and the output directory
   * in the compile setup.
   */
  def runRebase(cache: Option[File], rebase: Map[File, File]): Unit = {
    if (!rebase.isEmpty) {
      cache match {
        case None => throw new Exception("No cache file specified")
        case Some(cacheFile) =>
          val analysisStore = Compiler.analysisStore(cacheFile)
          analysisStore.get match {
            case None => throw new Exception("No analysis cache found at: " + cacheFile)
            case Some((analysis, compileSetup)) => {
              val multiRebasingMapper = createMultiRebasingMapper(rebase)
              val newAnalysis = rebaseAnalysis(analysis, multiRebasingMapper)
              val newSetup = rebaseSetup(compileSetup, multiRebasingMapper)
              analysisStore.set(newAnalysis, newSetup)
            }
          }
      }
    }
  }


  /**
   * Create a mapper function that performs multiple rebases. For a given file, it uses the first
   * rebase it finds that matches, if any. The order of rebases is underfined, so it's highly
   * recommended that there never be two rebases A1->B1, A2->B2 such that A1 is a prefix of A2.
   */
  def createMultiRebasingMapper(rebase: Map[File, File]): File => Option[File] = {
    val mappers = rebase map { x: (File, File) => Path.rebase(x._1, x._2) } toList

    @tailrec
    def tryRebase(f: File, mappers: List[File => Option[File]]): Option[File] = mappers match {
      case Nil => None
      case mapper :: tail => mapper(f) match {
        case None => tryRebase(f, tail)
        case fileOpt => fileOpt
      }
    }

    tryRebase(_, mappers)
  }

  /**
   * Rebase all paths in an analysis.
   */
  def rebaseAnalysis(analysis: Analysis, mapper: File => Option[File]): Analysis = {
    analysis.copy(rebaseStamps(analysis.stamps, mapper), rebaseAPIs(analysis.apis, mapper),
      rebaseRelations(analysis.relations, mapper), rebaseInfos(analysis.infos, mapper))
  }

  def rebaseStamps(stamps: Stamps, mapper: File => Option[File]): Stamps = {
    def rebase[A](fileMap: Map[File, A]) = rebaseFileMap(fileMap, mapper)
    Stamps(rebase(stamps.products), rebase(stamps.sources), rebase(stamps.binaries), rebase(stamps.classNames))
  }

  def rebaseAPIs(apis: APIs, mapper: File => Option[File]): APIs = {
    APIs(rebaseFileMap(apis.internal, mapper), apis.external)
  }

  def rebaseRelations(relations: Relations, mapper: File => Option[File]): Relations = {
    def rebase(rel: Relation[File, File]) = rebaseRelation(rel, mapper)
    def rebaseExt(rel: Relation[File, String]) = rebaseExtRelation(rel, mapper)
    Relations.make(rebase(relations.srcProd), rebase(relations.binaryDep), rebase(relations.internalSrcDep),
      rebaseExt(relations.externalDep), rebaseExt(relations.classes))
  }

  def rebaseInfos(infos: SourceInfos, mapper: File => Option[File]): SourceInfos = {
    SourceInfos.make(rebaseFileMap(infos.allInfos, mapper))
  }

  def rebaseRelation(relation: Relation[File, File], mapper: File => Option[File]): Relation[File, File] = {
    def rebase(fileMap: Map[File, Set[File]]) = rebaseFileSetMap(rebaseFileMap(fileMap, mapper), mapper)
    Relation.make(rebase(relation.forwardMap), rebase(relation.reverseMap))
  }

  def rebaseExtRelation(relation: Relation[File, String], mapper: File => Option[File]): Relation[File, String] = {
    Relation.make(rebaseFileMap(relation.forwardMap, mapper), rebaseFileSetMap(relation.reverseMap, mapper))
  }

  def rebaseFileMap[A](fileMap: Map[File, A], mapper: File => Option[File]): Map[File, A] = {
    fileMap flatMap { case (f, a) => mapper(f) map { (_, a) } }
  }

  def rebaseFileSetMap[A](fileSetMap: Map[A, Set[File]], mapper: File => Option[File]): Map[A, Set[File]] = {
    fileSetMap mapValues { _ flatMap { f => mapper(f) } }
  }

  /**
   * Rebase the output directory of a compile setup.
   */
  def rebaseSetup(setup: CompileSetup, mapper: File => Option[File]): CompileSetup = {
    val output = Some(setup.output) collect { case single: SingleOutput => single.outputDirectory }
    output flatMap mapper map { dir => new CompileSetup(CompileOutput(dir), setup.options, setup.compilerVersion, setup.order) } getOrElse setup
  }

  /**
   * Run an analysis split. The analyses are split by source directory and overwrite
   * the mapped analysis cache files.
   */
  def runSplit(cache: Option[File], mapping: Map[Seq[File], File]): Unit = {
    if (mapping.nonEmpty) {
      val expandedMapping: Map[File, File] = for {
        (srcs, analysis) <- mapping
        src <- srcs
      } yield (src, analysis)
      cache match {
        case None => throw new Exception("No cache file specified")
        case Some(cacheFile) =>
          Compiler.analysisStore(cacheFile).get match {
            case None => throw new Exception("No analysis cache found at: " + cacheFile)
            case Some ((analysis, compileSetup)) =>
              for ((splitCacheOpt, splitAnalysis) <- analysis.groupBy(expandedMapping.get _)) {
                splitCacheOpt match {
                  case None =>
                  case Some(splitCache) => Compiler.analysisStore(splitCache).set(splitAnalysis, compileSetup)
                }
              }
          }
      }
    }
  }

  /**
   * Find all sources not in a specified set of sources.
   *
   * If set of sources is a single directory, finds all sources outside that directory.
   */
  def findOutsideSources(analysis: Analysis, sources: Seq[File]): Set[File] = {
    val pathSet = Set(sources map { f => f.getCanonicalPath } : _*)
    if (pathSet.size == 1 && sources.head.isDirectory)
      (analysis.relations.srcProd.all map (_._1) filter { src => IO.relativize(sources.head, src).isEmpty }).toSet
    else {
      (analysis.relations.srcProd.all map (_._1) filter { src => !pathSet.contains(src.getCanonicalPath) }).toSet
    }
  }

  /**
   * Run an analysis reload. The in-memory cache is updated from the specified file.
   */
  def runReload(cacheFiles: Seq[File]): Unit = {
    for (cacheFile <- cacheFiles) {
      Compiler.analysisCache.put(cacheFile, Compiler.createAnalysisStore(cacheFile))
    }
  }

  /**
   * Print readable analysis outputs, if configured.
   */
  def printOutputs(analysis: Analysis, outputRelations: Option[File], outputProducts: Option[File], cwd: Option[File], classesDirectory: File): Unit = {
    printRelations(analysis, outputRelations, cwd)
    printProducts(analysis, outputProducts, classesDirectory)
  }

  /**
   * Print analysis relations to file.
   */
  def printRelations(analysis: Analysis, output: Option[File], cwd: Option[File]): Unit = {
    for (file <- output) {
      val userDir = (cwd getOrElse Setup.Defaults.userDir) + "/"
      def noCwd(path: String) = path stripPrefix userDir
      def keyValue(kv: (Any, Any)) = "   " + noCwd(kv._1.toString) + " -> " + noCwd(kv._2.toString)
      def relation(r: Relation[_, _]) = (r.all.toSeq map keyValue).sorted.mkString("\n")
      import analysis.relations.{ srcProd, binaryDep, internalSrcDep, externalDep, classes }
      val relationStrings = Seq(srcProd, binaryDep, internalSrcDep, externalDep, classes) map relation
      val output = """
        |products:
        |%s
        |binary dependencies:
        |%s
        |source dependencies:
        |%s
        |external dependencies:
        |%s
        |class names:
        |%s
        """.trim.stripMargin.format(relationStrings: _*)
      sbt.IO.write(file, output)
    }
  }

  /**
   * Print just source products to file, relative to classes directory.
   */
  def printProducts(analysis: Analysis, output: Option[File], classesDirectory: File): Unit = {
    for (file <- output) {
      def relative(path: String) = Util.relativize(classesDirectory, new File(path))
      def keyValue(kv: (Any, Any)) = relative(kv._1.toString) + " -> " + relative(kv._2.toString)
      val output = (analysis.relations.srcProd.all.toSeq map keyValue).sorted.mkString("\n")
      sbt.IO.write(file, output)
    }
  }
}
