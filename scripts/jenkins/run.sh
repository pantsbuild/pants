#!/bin/sh

JENKINS_URL=$(/usr/local/jenkins/scripts/get_jenkins_url.py)
SLAVE_NAME=$(/usr/local/jenkins/scripts/get_slave_name.py)
SLAVE_AGENT_URL="${JENKINS_URL}computer/${SLAVE_NAME}/slave-agent.jnlp"

wget "${JENKINS_URL}jnlpJars/slave.jar" -O /jenkins/slave.jar

java -jar /jenkins/slave.jar -jnlpUrl ${SLAVE_AGENT_URL}
