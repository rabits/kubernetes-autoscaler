# Simple example of the Jenkins custom slave env container
FROM jenkinsci/jnlp-slave

USER root

RUN apt-get -qq update && apt-get -qq dist-upgrade \
    && apt-get install -qq -y --no-install-recommends \
        maven ant \
    && apt-get clean

USER jenkins
