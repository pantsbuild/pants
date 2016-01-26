#!/usr/bin/python
import os
import httplib
import string
import sys

conn = httplib.HTTPConnection("169.254.169.254")
conn.request("GET", "/latest/user-data")
userdata = conn.getresponse().read()

for arg in string.split(userdata, "&"):
    if arg.split("=")[0] == "JENKINS_URL":
        print arg.split("=")[1]
        sys.exit(0)

raise Exception("Couldn't find JENKINS_URL.  userdata: {}".format(userdata))
