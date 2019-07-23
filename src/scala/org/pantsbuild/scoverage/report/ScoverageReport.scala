package org.pantsbuild.scoverage.report

import java.io.File
import sbt.internal.util.ConsoleLogger
import org.apache.commons.io.FileUtils
import scopt.OParser

import scoverage.{ Coverage, IOUtils, Serializer }
import scoverage.report.{ ScoverageHtmlWriter, ScoverageXmlWriter }

object ScoverageReport {
  val Scoverage = "scoverage"

  // Copying the logger from org.pantsbuild.zinc.bootstrap
  // As per https://github.com/pantsbuild/pants/issues/6160, this is a workaround
  // so we can run zinc without $PATH (as needed in remoting).
  System.setProperty("sbt.log.format", "true")

  // Setting the logger
  val logger = ConsoleLogger.apply()

  case class ReportOptions(
    loadDataDir: Boolean,
    measurementsPath: String,
    sourcePath: String,
    reportPath: String,
    dataPath: String,
    writeHtml: Boolean,
    writeXml: Boolean,
    writeXmlDebug: Boolean,
    cleanOld: Boolean,
    targetFilters: Seq[String]) {
    val writeReports: Boolean = {
      val write = writeHtml || writeXml
      if (!write) {
        // we could end here, but we will still attempt to load the coverage and dump stats as info
        // to the log, so maybe somebody would want to run this w/o generating reports?
        logger.warn("No report output format specified, so no reports will be written.")
      }
      write
    }
  }

  object ReportOptions {
    def apply(settings: Settings): ReportOptions = {
      ReportOptions(
        loadDataDir = settings.loadDataDir,
        measurementsPath = settings.measurementsDirPath,
        sourcePath = settings.sourceDirPath,
        reportPath = settings.reportDirPath,
        dataPath = settings.dataDirPath,
        writeHtml = settings.writeHtmlReport,
        writeXml = settings.writeXmlReport,
        writeXmlDebug = settings.writeXmlDebug,
        cleanOld = settings.cleanOldReports,
        targetFilters = settings.targetFilters)
    }
  }
  /**
   *
   * @param dataDirs list of measurement directories for which coverage
   *                 report has to be generated
   * @return         [Coverage] object for the [dataDirs]
   */
  private def aggregatedCoverage(dataDirs: Seq[File]): Coverage = {
    var id = 0
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
          id = id + 1
          coverage add stmt.copy(id = id)
        }
      }
    }
    coverage
  }

  /**
   *
   * @param dataDirs list of measurement directories for which coverage
   *                 report has to be generated
   * @return         Coverage object wrapped in Option
   */
  private def aggregate(dataDirs: Seq[File]): Option[Coverage] = {
    logger.info(s"Found ${dataDirs.size} subproject scoverage data directories [${dataDirs.mkString(",")}]")
    if (dataDirs.nonEmpty) {
      Some(aggregatedCoverage(dataDirs))
    } else {
      None
    }
  }

  /**
   *
   * @param dataDir root directory to search under
   * @return        all the directories and subdirs containing scoverage files beginning at [dataDir]
   */
  def getAllCoverageDirs(dataDir: File, acc: Seq[File]): Seq[File] = {
    if (dataDir.listFiles.filter(_.isFile).toSeq.exists(_.getName contains "scoverage.coverage")) {
      dataDir.listFiles.filter(_.isDirectory).toSeq
        .foldRight(acc :+ dataDir) { (e, a) => getAllCoverageDirs(e, a) }
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
  def filterFiles(dataDir: File, options: ReportOptions): Seq[File] = {
    val targetFiles = options.targetFilters

    val coverareDirs = getAllCoverageDirs(dataDir, Seq())

    if (targetFiles.nonEmpty) {
      logger.info(s"Looking for targets: $targetFiles")
      coverareDirs.filter {
        file => targetFiles.exists(file.toString contains _)
      }
    } else {
      coverareDirs
    }
  }

  /**
   * Aggregating coverage from all the coverage measurements.
   */
  private def loadAggregatedCoverage(dataPath: String, options: ReportOptions): Option[Coverage] = {
    val dataDir: File = new File(dataPath)
    logger.info(s"Attempting to open scoverage data dir: [$dataDir]")
    if (dataDir.exists) {
      logger.info(s"Aggregating coverage.")
      val dataDirs: Seq[File] = filterFiles(dataDir, options)
      aggregate(dataDirs)
    } else {
      logger.error("Coverage directory does not exists.")
      None
    }
  }

  /**
   * Loads coverage data from the specified data directory.
   */
  private def loadCoverage(dataPath: String): Option[Coverage] = {
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
          Some(coverage)

        case false =>
          logger.error("Coverage file did not exist")
          None

      }
    } else {
      logger.error("Data dir did not exist!")
      None
    }

  }

  /**
   * Writes coverage reports usign the specified source path to the specified report directory.
   */
  private def writeReports(coverage: Coverage, options: ReportOptions): Unit = {
    val sourceDir = new File(options.sourcePath)
    val reportDir = new File(options.reportPath)
    val reportDirHtml = new File(options.reportPath + "/html")
    val reportDirXml = new File(options.reportPath + "/xml")

    if (sourceDir.exists) {
      if (options.cleanOld && reportDir.exists) {
        logger.info(s"Nuking old report directory [$reportDir].")
        FileUtils.deleteDirectory(reportDir)
      }

      if (!reportDir.exists) {
        logger.info(s"Creating HTML report directory [$reportDirHtml]")
        reportDirHtml.mkdirs
        logger.info(s"Creating XML report directory [$reportDirXml]")
        reportDirXml.mkdirs
      }

      if (options.writeHtml) {
        logger.info(s"Writing HTML scoverage reports to [$reportDirHtml]")
        new ScoverageHtmlWriter(Seq(sourceDir), reportDirHtml, None).write(coverage)
      }

      if (options.writeXml) {
        logger.info(s"Writing XML scoverage reports to [$reportDirXml]")
        new ScoverageXmlWriter(Seq(sourceDir), reportDirXml, false).write(coverage)
        if (options.writeXmlDebug) {
          new ScoverageXmlWriter(Seq(sourceDir), reportDirXml, true).write(coverage)
        }
      }
    } else {
      logger.error(s"Source dir [$sourceDir] does not exist")
    }

    logger.success(s"Statement coverage: ${coverage.statementCoverageFormatted}%")
    logger.success(s"Branch coverage:    ${coverage.branchCoverageFormatted}%")
  }

  def main(args: Array[String]): Unit = {
    OParser.parse(Settings.parser1, args, Settings()) match {
      case Some(settings) =>
        val reportOptions = ReportOptions(settings)

        reportOptions.loadDataDir match {
          case false =>
            loadAggregatedCoverage(reportOptions.measurementsPath, reportOptions) match {
              case Some(cov) =>
                logger.success("Coverage loaded successfully.")
                if (reportOptions.writeReports) {
                  writeReports(cov, reportOptions)
                }

              case None => logger.error("Failed to load coverage.")
            }
          case true =>
            loadCoverage(reportOptions.dataPath) match {
              case Some(cov) =>
                logger.success("Coverage loaded successfully!")
                if (reportOptions.writeReports) {
                  writeReports(cov, reportOptions)
                }
              case _ => logger.error("Failed to load coverage")
            }
        }

      case None => logger.error("Incorrect options supplied")
    }
  }
}
