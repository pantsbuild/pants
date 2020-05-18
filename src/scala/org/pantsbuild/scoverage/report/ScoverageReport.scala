package org.pantsbuild.scoverage.report

import java.io.File
import org.apache.commons.io.FileUtils
import java.util.concurrent.atomic.AtomicInteger

import org.slf4j.Logger
import org.slf4j.LoggerFactory

import scoverage.{ Coverage, IOUtils, Serializer }
import scoverage.report.{ CoberturaXmlWriter, ScoverageHtmlWriter, ScoverageXmlWriter }

object ScoverageReport {
  val Scoverage = "scoverage"

  // Setting the logger
  val logger: Logger = LoggerFactory.getLogger(Scoverage)

  /**
   *
   * @param dataDirs list of measurement directories for which coverage
   *                 report has to be generated
   * @return         [Coverage] object for the [dataDirs]
   */
  private def aggregatedCoverage(dataDirs: Seq[File]): Coverage = {
    var id = new AtomicInteger(0)
    val coverage = Coverage()
    dataDirs foreach { dataDir =>
      val coverageFile: File = Serializer.coverageFile(dataDir)
      if (coverageFile.exists) {
        val subcoverage: Coverage = Serializer.deserialize(coverageFile)
        val measurementFiles: Array[File] = IOUtils.findMeasurementFiles(dataDir)
        val measurements = IOUtils.invoked(measurementFiles.toIndexedSeq)
        subcoverage.apply(measurements)
        subcoverage.statements foreach { stmt =>
          // need to ensure all the ids are unique otherwise the coverage object will have stmt collisions
          coverage add stmt.copy(id = id.incrementAndGet())
        }
      }
    }
    coverage
  }

  /**
   *
   * @param dataDirs list of measurement directories for which coverage
   *                 report has to be generated
   * @return         Coverage object
   */
  private def aggregate(dataDirs: Seq[File]): Coverage = {
    logger.info(s"Found ${dataDirs.size} subproject scoverage data directories [${dataDirs.mkString(",")}]")
    if (dataDirs.nonEmpty) {
      aggregatedCoverage(dataDirs)
    } else {
      throw new RuntimeException(s"No scoverage data directories found.")
    }
  }

  /**
   *
   * @param dataDir root directory to search under
   * @return        all the directories and subdirs containing scoverage files beginning at [dataDir]
   */
  def getAllCoverageDirs(dataDir: File, acc: Vector[File]): Vector[File] = {
    if (dataDir.listFiles.filter(_.isFile).toSeq.exists(_.getName contains "scoverage.coverage")) {
      dataDir.listFiles.filter(_.isDirectory).toSeq
        .foldRight(dataDir +: acc) { (e, a) => getAllCoverageDirs(e, a) }
    } else {
      dataDir.listFiles.filter(_.isDirectory).toSeq
        .foldRight(acc) { (e, a) => getAllCoverageDirs(e, a) }
    }
  }
  /**
   * Select the appropriate directories for which the scoverage report has
   * to be generated. If [targetFiles] is empty, report is generated for all
   * measurements directories inside in [dataDir].
   */
  def filterFiles(dataDir: File, settings: Settings): Vector[File] = {
    val targetFiles = settings.targetFilters

    val coverageDirs = getAllCoverageDirs(dataDir, Vector())

    if (targetFiles.nonEmpty) {
      logger.info(s"Looking for targets: $targetFiles")
      coverageDirs.filter {
        file => targetFiles.exists(file.toString contains _)
      }
    } else {
      coverageDirs
    }
  }

  /**
   * Aggregating coverage from all the coverage measurements.
   */
  private def loadAggregatedCoverage(dataPath: String, settings: Settings): Coverage = {
    val dataDir: File = new File(dataPath)
    logger.info(s"Attempting to open scoverage data dir: [$dataDir]")
    if (dataDir.exists) {
      logger.info(s"Aggregating coverage.")
      val dataDirs: Seq[File] = filterFiles(dataDir, settings)
      aggregate(dataDirs)
    } else {
      logger.error("Coverage directory does not exist.")
      throw new RuntimeException("Coverage directory does not exist.")
    }
  }

  /**
   * Loads coverage data from the specified data directory.
   */
  private def loadCoverage(dataPath: String): Coverage = {
    val dataDir: File = new File(dataPath)
    logger.info(s"Attempting to open scoverage data dir [$dataDir]")

    if (dataDir.exists) {
      val coverageFile = Serializer.coverageFile(dataDir)
      logger.info(s"Reading scoverage instrumentation [$coverageFile]")

      coverageFile.exists match {
        case true =>
          val coverage = Serializer.deserialize(coverageFile)
          logger.info(s"Reading scoverage measurements...")

          val measurementFiles = IOUtils.findMeasurementFiles(dataDir)
          val measurements = IOUtils.invoked(measurementFiles)
          coverage.apply(measurements)
          coverage

        case false =>
          logger.error("Coverage file did not exist")
          throw new RuntimeException("Coverage file did not exist")

      }
    } else {
      logger.error("Data dir did not exist!")
      throw new RuntimeException("Data dir did not exist!")
    }

  }

  /**
   *
   * Cleans and makes the report directory.
   */
  private def prepareFile(file: File, settings: Settings, fileType: String): Unit = {
    if (settings.cleanOldReports) {
      logger.info(s"Nuking old $fileType report directories.")
      if (file.exists) FileUtils.deleteDirectory(file)
    }
    if (!file.exists) {
      logger.info(s"Creating $fileType report directory [$file]")
      file.mkdirs
    }
  }
  /**
   * Writes coverage reports usign the specified source path to the specified report directory.
   */
  private def writeReports(coverage: Coverage, settings: Settings): Unit = {
    val sourceDir = new File(settings.sourceDirPath)
    if (sourceDir.exists) {

      if (!settings.htmlDirPath.isEmpty) {
        val reportDirHtml = new File(settings.htmlDirPath)
        prepareFile(reportDirHtml, settings, "html")
        logger.info(s"Writing HTML scoverage reports to [$reportDirHtml]")
        new ScoverageHtmlWriter(Seq(sourceDir), reportDirHtml, None).write(coverage)
      }

      if (!settings.xmlDirPath.isEmpty) {
        val reportDirXml = new File(settings.xmlDirPath)
        prepareFile(reportDirXml, settings, "xml")
        logger.info(s"Writing XML scoverage reports to [$reportDirXml]")
        new ScoverageXmlWriter(Seq(sourceDir), reportDirXml, false).write(coverage)

        if (settings.outputAsCobertura) {
          // Cobertura Output
          logger.info(s"Writing XML scoverage in Cobertura format reports to [$reportDirXml]")
          new CoberturaXmlWriter(Seq(sourceDir), reportDirXml).write(coverage)
        }
      }

      if (!settings.xmlDebugDirPath.isEmpty) {
        val reportDirXmlDebug = new File(settings.xmlDebugDirPath)
        prepareFile(reportDirXmlDebug, settings, "xml-debug")
        logger.info(s"Writing XML-Debug scoverage reports to [$reportDirXmlDebug]")
        new ScoverageXmlWriter(Seq(sourceDir), reportDirXmlDebug, true).write(coverage)
      }

    } else {
      logger.error(s"Source dir [$sourceDir] does not exist")
      throw new RuntimeException(s"Source dir [$sourceDir] does not exist")
    }

    logger.info(s"Statement coverage: ${coverage.statementCoverageFormatted}%")
    logger.info(s"Branch coverage:    ${coverage.branchCoverageFormatted}%")
  }

  def main(args: Array[String]): Unit = {
    Settings.parser1.parse(args, Settings()) match {
      case Some(settings) =>
        val writeScoverageReports = !settings.htmlDirPath.isEmpty || !settings.xmlDirPath.isEmpty ||
          !settings.xmlDebugDirPath.isEmpty

        settings.loadDataDir match {
          case false =>
            val cov = loadAggregatedCoverage(settings.measurementsDirPath, settings)
            logger.info("Coverage loaded successfully.")
            if (writeScoverageReports) {
              writeReports(cov, settings)
            } else throw new RuntimeException("No reports generated! See --help to specify type of report.")
          case true =>
            val cov = loadCoverage(settings.dataDirPath)
            logger.info("Coverage loaded successfully!")
            if (writeScoverageReports) {
              writeReports(cov, settings)
            } else throw new RuntimeException("No reports generated! See --help to specify type of report.")
        }

      case None => throw new RuntimeException("ScoverageReport: Incorrect options supplied.")
    }
  }
}
