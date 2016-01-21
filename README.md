Kubernetes Autoscaler
=====================
Script provides autoscaling functionality for the Kubernetes cluster and right now used for dinamically scaling Jenkins slaves capacity in GCE.

Each 10 seconds (by default) script collects info about cluster, checks thresholds and makes decision about actions: do nothing, create node or delete node.

## Examples:
### Options:
You can use options file `./autoscaler.py @options.txt` and list options by `-h`
```
--kubernetes-api-url
https://<kubernetes_master_ip>/api/v1
--kubernetes-user
admin
--kubernetes-token
<kubernetes_password>
--jenkins-url
http://104.155.62.177
--jenkins-user
jenkins
--jenkins-token
<jenkins_token>
--jenkins-capacity
7
--create-pods
0.7
--delete-pods
0.3
--delay-delete
300
--gce-instance-group-manager
kube-jenkins-minion-group
```

### Report output:
```
--- Thu Jan 21 14:09:21 2016 ---
Report:
  Cluster:
    pods: 0.388888888889
    cpu: 0.273333333333
    memory: 0.0720239836722

  Nodes:
    kube-jenkins-minion-b9nw: # State: RUNNING, Action: NONE, Pods: 1/6, CPU: 0/1, Mem: 0/3711MB
      Running jenkins-slave: 9e1e189121de
    kube-jenkins-minion-px7g: # State: RUNNING, Action: NONE, Pods: 1/6, CPU: 0/1, Mem: 0/3711MB
      Running jenkins-slave: 9dc7f1468f77
    kube-jenkins-minion-ill3: # State: RUNNING, Action: NONE, Pods: 5/6, CPU: 0.82/1, Mem: 802/3711MB

  Jenkins:
    Capacity: 13
    onlineExecutors: 2.000239
    availableExecutors: 0.000000
    connectingExecutors: 0.000000
    busyExecutors: 2.000239
    queueLength: 0.000001
    idleExecutors: 0.000000
    totalExecutors: 2.000239
    definedExecutors: 2.000239
    totalQueueLength: 0.000001
```
