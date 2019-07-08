"""Download variation data from dbSNP and install within directory structure.

Uses Broad's GATK resource bundles:

 http://www.broadinstitute.org/gsa/wiki/index.php/GATK_resource_bundle
"""
import os

from fabric.api import *
from fabric.contrib.files import *

def download_dbsnp(genomes, bundle_version, dbsnp_version):
    """Download and install dbSNP variation data for supplied genomes.
    """
    folder_name = "variation"
    genome_dir = os.path.join(env.data_files, "genomes")
    for (orgname, gid, manager) in ((o, g, m) for (o, g, m) in genomes
                                    if m.config.get("dbsnp", False)):
        vrn_dir = os.path.join(genome_dir, orgname, gid, folder_name)
        if not exists(vrn_dir):
            run('mkdir -p %s' % vrn_dir)
        with cd(vrn_dir):
            _download_broad_dbsnp_bundle(gid, bundle_version, dbsnp_version)

def _download_broad_dbsnp_bundle(gid, bundle_version, dbsnp_version):
    broad_fname = "dbsnp_{ver}.{gid}.vcf".format(ver=dbsnp_version, gid=gid)
    fname = broad_fname.replace(".{0}".format(gid), "")
    base_url = "ftp://gsapubftp-anonymous:@ftp.broadinstitute.org/bundle/" + \
               "{bundle}/{gid}/{fname}.gz".format(
                   bundle=bundle_version, fname=broad_fname, gid=gid)
    if not exists(fname):
        run("wget %s" % base_url)
        run("gunzip %s" % os.path.basename(base_url))
        run("mv %s %s" % (broad_fname, fname))
    return fname
