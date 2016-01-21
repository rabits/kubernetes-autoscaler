#!/bin/sh
# Example script for simple preparing of the Kubernetes cluster in GCE
export KUBERNETES_PROVIDER=gce
export KUBE_GCE_INSTANCE_PREFIX=kube-jenkins
export KUBE_GCE_ZONE=europe-west1-b
export MASTER_SIZE=n1-standard-1

export KUBE_ENABLE_CLUSTER_MONITORING=influxdb

export MINION_SIZE=n1-standard-1
export NUM_MINIONS=1
export MINION_DISK_SIZE=100GB

export KUBE_UP_AUTOMATIC_CLEANUP=true

export KUBELET_TEST_ARGS="--max-pods=7"

curl -sS https://get.k8s.io | bash
