/**
 * Copyright (C) 2012 Typesafe, Inc. <http://www.typesafe.com>
 */

package org.pantsbuild.zinc

import java.io.File
import java.nio.charset.Charset
import sbt.compiler.CompileOutput
import sbt.inc.{ APIs, Analysis, Relations, SourceInfos, Stamps }
import sbt.{ CompileSetup, Logger, Relation, Using }
import xsbti.compile.SingleOutput


object SbtAnalysis {

  /**
   * Run analysis manipulation utilities.
   */
  def runUtil(util: AnalysisUtil, log: Logger,
              mirrorAnalysis: Boolean = false,
              cwd: Option[File] = None): Unit = {
    runMerge(util.cache, util.merge, mirrorAnalysis, cwd)
    runRebase(util.cache, util.rebase, mirrorAnalysis, cwd)
    runSplit(util.cache, util.split, mirrorAnalysis, cwd)
    runReload(util.reload)
  }

  /**
   * Run an analysis merge. The given analyses should share the same compile setup.
   * The merged analysis will overwrite whatever is in the combined analysis cache.
   */
  def runMerge(combinedCache: Option[File], cacheFiles: Seq[File],
               mirrorAnalysis: Boolean = false,
               cwd: Option[File] = None): Unit = {
    if (cacheFiles.nonEmpty) {
      combinedCache match {
        case None => throw new Exception("No cache file specified")
        case Some(cacheFile) =>
          val analysisStore = Compiler.analysisStore(cacheFile)
          mergeAnalyses(cacheFiles) match {
            case Some((mergedAnalysis, mergedSetup)) => {
                analysisStore.set(mergedAnalysis, mergedSetup)
                if (mirrorAnalysis) {
                  printRelations(mergedAnalysis, Some(new File(cacheFile.getPath() + ".relations")), cwd)
                }
              }
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
    val analysesAndSetups: Seq[(Analysis, CompileSetup)] = cacheFiles flatMap { Compiler.analysisStore(_).get() }
    val mergedAnalysis = Analysis.merge(analysesAndSetups map {_._1})
    analysesAndSetups.lastOption map { x: (Analysis, CompileSetup) => (mergedAnalysis, x._2) }
  }

  /**
   * Run an analysis rebase. Rebase all paths in the analysis, and the output directory
   * in the compile setup.
   */
  def runRebase(cache: Option[File], rebase: Map[File, File],
                mirrorAnalysis: Boolean, cwd: Option[File]): Unit = {
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
              if (mirrorAnalysis) {
                printRelations(newAnalysis, Some(new File(cacheFile.getPath() + ".relations")), cwd)
              }
            }
          }
      }
    }
  }


  /**
   * Create a mapper function that performs multiple rebases. For a given file, it uses the first rebase
   * it finds in which the source base is a prefix of the file path. If no matching rebase is found, it
   * returns the original path unchanged.
   *
   * The order of rebases is undefined, so it's highly recommended that there never be two
   * rebases A1->B1, A2->B2 such that A1 is a prefix of A2.
   *
   * Note that this doesn't need to do general-purpose relative rebasing for paths with ../ etc. So it
   * uses a naive prefix-matching algorithm.
   */

  def createMultiRebasingMapper(rebase: Map[File, File]): File => Option[File] = {
    def createSingleRebaser(fromBase: String, toBase: Option[String]): PartialFunction[String, Option[String]] = {
      case path if path.startsWith(fromBase) => { toBase.map(_ + path.substring(fromBase.length)) }
    }

    val rebasers: List[PartialFunction[String, Option[String]]] =
      (rebase map { x: (File, File) =>
        createSingleRebaser(x._1.getAbsolutePath, if (x._2.getPath.isEmpty) None else Some(x._2.getAbsolutePath))
      }).toList

    val multiRebaser: PartialFunction[String, Option[String]] =
      rebasers reduceLeft (_ orElse _) orElse { case s: String => Some(s) }
    f: File => multiRebaser(f.getAbsolutePath) map { new File(_) }
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
    Relations.make(rebase(relations.srcProd), rebase(relations.binaryDep),
      Relations.makeSource(rebase(relations.direct.internal), rebaseExt(relations.direct.external)),
      Relations.makeSource(rebase(relations.publicInherited.internal), rebaseExt(relations.publicInherited.external)),
      rebaseExt(relations.classes))
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
    output flatMap mapper map { dir => new CompileSetup(CompileOutput(dir), setup.options, setup.compilerVersion, setup.order, setup.nameHashing) } getOrElse setup
  }

  /**
   * Run an analysis split. The analyses are split by source directory and overwrite
   * the mapped analysis cache files.
   */
  def runSplit(cache: Option[File], mapping: Map[Seq[File], File],
              mirrorAnalysis: Boolean = false,
              cwd: Option[File] = None): Unit = {
    if (mapping.nonEmpty) {
      val expandedMapping: Map[File, File] = for {
        (srcs, analysis) <- mapping
        src <- srcs
      } yield (src, analysis)
      // A split with no specified source files acts as a "catch-all", for analysis
      // belonging to source files not specified on any other split.
      val catchAll: Option[File] = mapping.find( { _._1.isEmpty } ) map { _._2 }
      def discriminator(f: File): Option[File] = expandedMapping.get(f) match {
        case None => catchAll
        case s => s
      }
      cache match {
        case None => throw new Exception("No cache file specified")
        case Some(cacheFile) =>
          Compiler.analysisStore(cacheFile).get() match {
            case None => throw new Exception("No analysis cache found at: " + cacheFile)
            case Some ((analysis, compileSetup)) => {
              def writeAnalysis(cacheFile: File, analysis: Analysis) {
                Compiler.analysisStore(cacheFile).set(analysis, compileSetup)
                if (mirrorAnalysis) {
                  printRelations(analysis, Some(new File(cacheFile.getPath + ".relations")), cwd)
                }
              }
              val grouped: Map[Option[File], Analysis] = analysis.groupBy(discriminator)
              for ((splitCacheOpt, splitAnalysis) <- grouped) {
                splitCacheOpt match {
                  case Some(splitCache) => writeAnalysis(splitCache, splitAnalysis)
                  case None =>
                }
              }
              // Some groups may be empty, but we still want to write something out.
              val emptySplits: Set[File] = mapping.values.toSet -- grouped.keySet.flatten
              for (file <- emptySplits) {
                writeAnalysis(file, Analysis.Empty)
              }
            }
          }
      }
    }
  }

  /**
   * Run an analysis reload. The in-memory cache is updated from the specified file.
   */
  def runReload(cacheFiles: Seq[File]): Unit = {
    // TODO: Do we still need reload functionality now that we cache by fingerprint?
    for (cacheFile <- cacheFiles) {
      Compiler.analysisStore(cacheFile).get()
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
      Using.fileWriter(utf8)(file) { out =>
        def writeNoCwd(s: String) = if (s.startsWith(userDir)) out.write(s, userDir.length, s.length - userDir.length) else out.write(s)
        def printRelation(header: String, r: Relation[File, _]) {
          out.write(header + ":\n")
          r._1s.toSeq.sorted foreach { k =>
            r.forward(k).toSeq.map(_.toString).sorted foreach { v =>
              out.write("   "); writeNoCwd(k.toString); out.write(" -> "); writeNoCwd(v); out.write("\n")
            }
          }
        }
        val sections =
          ("products", analysis.relations.srcProd) ::
          ("binary dependencies", analysis.relations.binaryDep) ::
          ("source dependencies", analysis.relations.internalSrcDep) ::
          ("external dependencies", analysis.relations.externalDep) ::
          ("class names", analysis.relations.classes) ::
          Nil
        sections foreach { x => printRelation(x._1, x._2) }
      }
    }
  }

  /**
   * Print just source products to file, relative to classes directory.
   */
  def printProducts(analysis: Analysis, output: Option[File], classesDirectory: File): Unit = {
    for (file <- output) {
      Using.fileWriter(utf8)(file) { out =>
        def relative(path: File) = Util.relativize(classesDirectory, path)
        analysis.relations.srcProd._1s.toSeq.sorted foreach {  k =>
          analysis.relations.srcProd.forward(k).toSeq.sorted foreach { v =>
            out.write(relative(k)); out.write(" -> "); out.write(relative(v)); out.write("\n")
          }
        }
      }
    }
  }

  private[this] val utf8 =  Charset.forName("UTF-8")
}
