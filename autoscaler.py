#!/usr/bin/env python
'''Autoscaler 1.0
Author: Rabits <home@rabits.org>
Description: Script provides autoscale daemon for the Kubernetes cluster
Requirements: urllib3, run in gce instance with compute rights
'''

import urllib3
import json, time
from threading import Timer

class Request(object):
    '''Simple http/https request class'''
    def __init__(self, api_url = 'https://localhost/api/v1',
            user = None, password = None,
            headers = None, cert = None):

        self._headers = headers if headers else {}
        if user and password:
            self._headers.update(urllib3.util.make_headers(basic_auth=':'.join([user, password])))

        self._api_url = api_url
        if api_url.startswith('https://'):
            # TODO: check cert
            self._urlpool = urllib3.PoolManager(cert_reqs='CERT_REQUIRED' if cert else 'CERT_NONE', ca_certs=None)
        else:
            self._urlpool = urllib3.PoolManager()

    def json(self, json_string):
        '''Parse json & return dict'''
        try:
            return json.loads(json_string)
        except ValueError:
            raise Exception({'message': 'Response parsing error: %s' % json_string})

    def api(self):
        return self._api_url

    def setHeaders(self, headers):
        self._headers = headers

    def get(self, request, data = None, api_url = None):
        '''Do GET request to api'''
        response = self._urlpool.request('GET', '%s/%s' % (
            api_url if api_url else self._api_url,
            request), headers = self._headers)
        if( response.status != 200 ):
            raise Exception({'message': 'Got status error: %d, %s (%s)' % (response.status, response.data, request)})

        return response.data

    def post(self, request, data = None, api_url = None, content_type = 'application/json'):
        '''Do POST request to api'''
        newheaders = {'Content-Type': content_type, 'Content-Length': len(data) if data else 0}
        newheaders.update(self._headers)
        response = self._urlpool.urlopen('POST', '%s/%s' % (
            api_url if api_url else self._api_url,
            request), body=data, headers=newheaders)
        if( response.status != 200 ):
            raise Exception({'message': 'Got status error: %d, %s (%s)' % (response.status, response.data, request)})

        return response.data

class KubernetesApi(object):
    '''Provides access to Kubernetes API'''
    def __init__(self, request_obj):
        self._req = request_obj

    def getNodes(self):
        '''Get current nodes list'''
        return self._req.json(self._req.get('nodes'))

    def getPods(self):
        '''Get current pods list'''
        return self._req.json(self._req.get('pods'))


class GCEApi(object):
    '''Provides access to Google Compute Engine API'''
    def __init__(self, request_obj = None, proj_zone = None):
        self._req = request_obj if request_obj else Request('https://www.googleapis.com/compute/v1')
        self._meta_req = Request('http://metadata/computeMetadata/v1', headers={'Metadata-Flavor':'Google'})
        self._update_token_timer = None
        if proj_zone:
            self._proj_zone = proj_zone
        else:
            try:
                self._proj_zone = self._meta_req.get('instance/zone')
            except:
                raise Exception({'message': 'Unable get instance metadata with project & zone'})

        self.updateToken()

    def stop(self):
        '''Stops GCE Api timer'''
        if self._update_token_timer:
            self._update_token_timer.cancel()

    def updateToken(self):
        '''Updates access token header'''
        try:
            json_string = self._meta_req.get('instance/service-accounts/default/token')
            data = json.loads(json_string)
            self._req.setHeaders({'Authorization': '%s %s' % (data['token_type'], data['access_token'])})
            self._update_token_timer = Timer(int(data['expires_in']) - 5, self.updateToken)
            self._update_token_timer.start()
        except ValueError:
            raise Exception({'message': 'Unable to parse token json: %s' % json_string})
        except:
            raise Exception({'message': 'Unable get GCE service-account token'})

    def getInstances(self):
        return self._req.json(self._req.get('%s/instances' % self._proj_zone))

    def getInstanceGroupManager(self, name):
        out = self._req.json(self._req.get('%s/instanceGroupManagers/%s' % (self._proj_zone, name)))
        out.update(self._req.json(self._req.post('%s/instanceGroupManagers/%s/listManagedInstances' % (self._proj_zone, name))))
        return out

    def getOperation(self, name):
        return self._req.json(self._req.get('%s/operations/%s' % (self._proj_zone, name)))

    def resizeGroupInstance(self, group_name, size):
        return self._req.json(self._req.post('%s/instanceGroupManagers/%s/resize?size=%d' % (self._proj_zone, group_name, size)))

    def deleteGroupInstances(self, group_name, instances):
        instances = [ '%s/%s/instances/%s' % (self._req.api(), self._proj_zone, i) for i in (instances if isinstance(instances, list) else [instances]) ]
        return self._req.json(self._req.post('%s/instanceGroupManagers/%s/deleteInstances' % (self._proj_zone, group_name),
            data = json.dumps({"instances": instances})))

class JenkinsApi(object):
    '''Provides access to jenkins functionality'''
    def __init__(self, request_obj):
        self._req = request_obj

    def _parseGroovyResponse(self, result_string):
        '''Parse & return dict with output before and result after "Result: " string'''
        out = result_string.rsplit('Result: ', 1)
        return {'output': out[0], 'result': out[1][:-1] if len(out) > 1 else None}

    def setCloudCap(self, cloud_name, cap):
        return self._parseGroovyResponse(self._req.post('scriptText', content_type = 'application/x-www-form-urlencoded', data = (
            '''script=def cloud = Jenkins.instance.clouds.getByName({name!r})\n'''
            '''def newcloud = cloud.getClass().newInstance('''
            '''  cloud.name, cloud.getTemplates(), cloud.getServerUrl(), cloud.getNamespace(),'''
            '''  cloud.getJenkinsUrl(), "{cap:d}", 30, 30, cloud.getRetentionTimeout())\n'''
            '''newcloud.setCredentialsId(cloud.getCredentialsId())\n'''
            '''newcloud.setSkipTlsVerify(cloud.isSkipTlsVerify())\n'''
            '''newcloud.setJenkinsTunnel(cloud.getJenkinsTunnel())\n'''
            '''Jenkins.instance.clouds.replace(cloud, newcloud)'''
            ).format(name=cloud_name, cap=cap)))

    def getCloudCap(self, cloud_name):
        '''Returns current cloud container cap'''
        return int(self._parseGroovyResponse(self._req.post('scriptText', content_type = 'application/x-www-form-urlencoded',
            data = '''script=Jenkins.instance.clouds.getByName({name!r}).getContainerCapStr()'''.format(name=cloud_name)))['result'])

    def getQueue(self):
        '''Returns current queued items'''
        return self._req.json(self._req.get('queue/api/json'))

    def getLoad(self):
        '''Returns current load on jenkins'''
        return self._req.json(self._req.get('overallLoad/api/json?tree=*[sec10[latest]]'))


class Autoscaler(object):
    '''Provides autoscale daemon functions'''
    def __init__(self, options, kube_api_obj, gce_api_obj = None, jenkins_obj = None):
        self._cfg = {}
        self._overrides = {}
        self._thresholds = {}
        self._parseCfg(options)

        self._kapi = kube_api_obj
        self._gapi = gce_api_obj if gce_api_obj else GCEApi()
        self._japi = jenkins_obj

        self._running = False
        self._nodes = {}
        self._average = {}
        self._group_status = {}
        self._actions = []

        self._suffixes = {
            'Ki': 2**10, 'Mi': 2**20, 'Gi': 2**30, 'Ti': 2**40, 'Pi': 2**50, 'Ei': 2**60,
            'n': 10**-9, 'u': 10**-6, 'm': 10**-3, 'k': 10**3, 'M': 10**6, 'G': 10**9, 'T': 10**12, 'P': 10**15, 'E': 10**18
        }

    def _parseCfg(self, cfg):
        self._cfg = cfg
        self._thresholds = {
            'create': {},
            'delete': {}
        }

        if not self._cfg['gce/instance-group-manager']:
            raise Exception('ERROR: Please set --gce-instance-group-manager option')

        if not self._cfg['jenkins/cluster-name']:
            self._cfg['jenkins/cluster-name'] = self._cfg['gce/instance-group-manager']

        for key in self._cfg:
            if cfg[key] != None:
                keys = key.split('/', 1)
                if keys[0] == 'override':
                    self._overrides[keys[1]] = cfg[key]
                elif keys[0] in self._thresholds:
                    self._thresholds[keys[0]][keys[1]] = cfg[key]

    def _suffix(self, value):
        '''Convert value with suffix to numeric value'''
        if not value[-1].isdigit():
            if not value[-2].isdigit():
                value, suffix = int(value[0:-2]), value[-2:]
            else:
                value, suffix = int(value[0:-1]), value[-1:]
            value *= self._suffixes[suffix]
        else:
            value = int(value)

        return value

    def _getStatusAverage(self, status):
        l = [ self._nodes[p]['status'][status] for p in self._nodes ]
        m = [ self._nodes[p]['status']['%s_max' % status] for p in self._nodes ]
        return float(sum(l))/(sum(m)) if len(l) > 0 else 0

    def _actionInProgress(self):
        # TODO: multi-actions or action change should be available
        # If action exist in the list
        if len(self._actions) > 0:
            return True

        # Check current actions of group manager
        actions = self._group_status['currentActions'].copy()
        actions.pop('none')
        if sum(actions.values()) > 0:
            return True

        # Check available nodes actions
        actions = [ node['action'] for node in self._nodes.values() if node['action'] != 'NONE' ]
        if len(actions) > 0:
            return True

        return False

    def _newAction(self, action):
        # TODO: simple implementation for the demo
        if not self._actionInProgress():
            self._actions.append({
                'delay': self._cfg['delay/%s' % action],
                'action': action
            })

    def _node(self, data = {}):
        return {
            'data': data,
            'pods': [],
            'status': {
                'pods_max': 0,
                'pods': 0,
                'cpu_max': 0,
                'cpu': 0,
                'memory_max': 0,
                'memory': 0
            },
            'state': None,
            'action': None
        }

    def updateInfo(self):
        new_nodes = {}

        # TODO: use streams to retreive updated data online
        pods = self._kapi.getPods()['items']
        nodes = self._kapi.getNodes()['items']
        self._group_status = self._gapi.getInstanceGroupManager(self._cfg['gce/instance-group-manager'])

        for node in nodes:
            new_nodes[node['metadata']['name']] = self._node(node)

        for pod in pods:
            node = pod['spec']['nodeName'] if 'nodeName' in pod['spec'] else 'UNKNOWN'
            if not node in new_nodes:
                new_nodes[node] = self._node(None)
                new_nodes[node]['action'] = 'NONE'

            # Ignore minion node agents
            if not pod['metadata']['name'].endswith(node):
               new_nodes[node]['pods'].append(pod)

        for node in new_nodes:
            if node == 'UNKNOWN':
                continue
            n = new_nodes[node]
            req = [ c['resources']['requests'] for sublist in [ p['spec']['containers'] for p in n['pods'] ] for c in sublist if 'requests' in c['resources'] ]
            cpu = [ self._suffix(r['cpu']) for r in req if 'cpu' in r ]
            memory = [ self._suffix(r['memory']) for r in req if 'memory' in r ]
            new_nodes[node]['status'] = {
                'pods_max': int(new_nodes[node]['data']['status']['capacity']['pods']) - 1, # except node daemon pod
                'pods': len(new_nodes[node]['pods']),
                'cpu_max': self._suffix(new_nodes[node]['data']['status']['capacity']['cpu']),
                'cpu': sum(cpu),
                'memory_max': self._suffix(new_nodes[node]['data']['status']['capacity']['memory']),
                'memory': sum(memory)
            }
            for key in self._overrides:
                new_nodes[node]['status'][key] = self._overrides[key]

        for i in self._group_status['managedInstances']:
            node_name = i['instance'].rsplit('/', 1)[-1]
            if node_name in new_nodes:
                n = new_nodes[node_name]
                n['action'] = i['currentAction'] if 'currentAction' in i else None
                n['state'] = i['instanceStatus'] if 'instanceStatus' in i else None
            else:
                new_nodes[node_name] = self._node()

        # TODO: use kubernetes history to update just changed data
        self._nodes = new_nodes

        self._average = {
            'pods': self._getStatusAverage('pods'),
            'cpu': self._getStatusAverage('cpu'),
            'memory': self._getStatusAverage('memory')
        }

    def checkThresholds(self):
        for thr in self._thresholds['create']:
            if self._average[thr] > self._thresholds['create'][thr]:
                if len(self._nodes) < self._cfg['kubernetes/max-minions']:
                    return 1
                else:
                    return 0

        for thr in self._thresholds['delete']:
            if self._average[thr] < self._thresholds['delete'][thr]:
                return -1

        return 0

    def processActions(self):
        todel_actions = []
        for a in self._actions:
            if a['action'] == 'create' and self._check_thresholds <= 0:
                print 'INFO: Cluster no more required enlargement'
                todel_actions.append(a)
                continue
            elif a['action'] == 'delete' and self._check_thresholds >= 0:
                print 'INFO: Cluster no more required reduction'
                todel_actions.append(a)
                continue

            if a['delay'] > 0:
                print 'INFO: Delay action "%s"' % a['action']
                a['delay'] -= self._cfg['sleep-time']
            else:
                # Get threshold
                if a['action'] == 'create':
                    print 'INFO: Exec create action'
                    self._gapi.resizeGroupInstance(self._cfg['gce/instance-group-manager'], self._group_status['targetSize']+1)
                    todel_actions.append(a)
                    if self._japi:
                        cap = self._japi.getCloudCap(self._cfg['jenkins/cluster-name'])
                        cap += self._nodes.values()[0]['status']['pods_max']
                        self._japi.setCloudCap(self._cfg['jenkins/cluster-name'], cap)
                        print 'INFO: Jenkins cluster capacity increased to %d' % cap
                elif a['action'] == 'delete':
                    # Select first empty node to delete
                    # TODO: prepare node to deletion - disconnect it from the kubernetes cluster
                    empty_node_names = [ n for n in self._nodes if self._nodes[n]['status']['pods'] == 0 and self._nodes[n]['action'] == 'NONE' ]
                    if len(empty_node_names) > 0:
                        node_name = empty_node_names.pop()
                        print 'INFO: Exec delete action on %s' % node_name
                        self._gapi.deleteGroupInstances(self._cfg['gce/instance-group-manager'], node_name)
                        todel_actions.append(a)
                        if self._japi:
                            cap = self._japi.getCloudCap(self._cfg['jenkins/cluster-name'])
                            cap -= self._nodes.values()[0]['status']['pods_max']
                            if cap < self._cfg['jenkins/capacity']:
                                cap = self._cfg['jenkins/capacity']
                            self._japi.setCloudCap(self._cfg['jenkins/cluster-name'], cap)
                            print 'INFO: Jenkins cluster capacity reduced to %d' % cap
                    else:
                        print 'INFO: Unable to delete node - waiting until any node was empty'
                else:
                    print 'WARNING: unknown action "%s"' % a['action']
                    todel_actions.append(a)

        # Clean executed actions
        for d in todel_actions:
            self._actions.remove(d)

    def printReport(self):
        print 'Report:'

        print '  Cluster:'
        for avg in self._average:
            print '    {}: {}'.format(avg, self._average[avg])

        print
        print '  Nodes:'
        for node in self._nodes:
            n = self._nodes[node]
            print '    {name}: # State: {state}, Action: {action}, Pods: {pods}/{pods_max}, CPU: {cpu}/{cpu_max}, Mem: {mem}/{mem_max}MB'.format(
                name = node,
                state = n['state'], action = n['action'],
                pods = n['status']['pods'], pods_max = n['status']['pods_max'],
                cpu = n['status']['cpu'], cpu_max = n['status']['cpu_max'],
                mem = n['status']['memory']/1048576, mem_max = n['status']['memory_max']/1048576
            )
            for pod in n['pods']:
                if not pod['metadata']['namespace'] in [ name.strip() for name in self._cfg['report/ignore-namespaces'].split(',') ]:
                    print '      %s %s: %s' % (pod['status']['phase'], pod['metadata']['namespace'], pod['metadata']['name'])

        if len(self._actions) > 0:
            print
            print '  Actions:'
            for a in self._actions:
                print '    - {}: {}s'.format(a['action'], a['delay'])

        if self._japi:
            print
            print '  Jenkins:'
            print '    Capacity: %d' % self._japi.getCloudCap(self._cfg['jenkins/cluster-name'])
            load = self._japi.getLoad()
            for i in load:
                print '    %s: %f' % (i, load[i]['sec10']['latest'])

        print

    def run(self):
        self._running = True
        while self._running:
            try:
                try:
                    print '--- %s ---' % time.strftime('%c')
                    self.updateInfo()

                    self._check_thresholds = self.checkThresholds()
                    if self._check_thresholds > 0:
                        self._newAction('create')
                    elif self._check_thresholds < 0:
                        self._newAction('delete')

                    self.processActions()
                    self.printReport()
                except Exception as e:
                    print 'Warning: %s' % e
                    import traceback
                    traceback.print_exc()
                except:
                    print 'Unknown exception'

                time.sleep(self._cfg['sleep-time'])
            except (KeyboardInterrupt, SystemExit):
                print 'Exiting'
                break
            except:
                print 'Abnormal exiting'
                self.stop()
                raise
        self.stop()

    def stop(self):
        self._running = False
        self._gapi.stop()

if __name__ == "__main__":
    from argparse import ArgumentParser

    parser = ArgumentParser(usage='./%(prog)s [options] [@argsfile]', description=__doc__, fromfile_prefix_chars='@')
    parser.add_argument("--kubernetes-api-url", dest="kubernetes/api-url", metavar="APIURL", help="Kubernetes: url api like https://<host>/api/v1")
    parser.add_argument("--kubernetes-user", dest="kubernetes/user", metavar="NAME", help="Kubernetes: user name or service account")
    parser.add_argument("--kubernetes-token", dest="kubernetes/token", metavar="TOKEN", help="Kubernetes: token or user password")
    parser.add_argument("--kubernetes-max-minions", dest="kubernetes/max-minions", type=int, default=100, metavar="NUM", help="Kubernetes: maximum cluster size")
    parser.add_argument("--gce-instance-group-manager", dest="gce/instance-group-manager", metavar="NAME", help="Instance group manager with kubernetes minions")
    parser.add_argument("--jenkins-url", dest="jenkins/url", metavar="URL", help="Jenkins: url api like https://<host>")
    parser.add_argument("--jenkins-user", dest="jenkins/user", metavar="NAME", help="Jenkins: user name or service account")
    parser.add_argument("--jenkins-token", dest="jenkins/token", metavar="TOKEN", help="Jenkins: token or user password")
    parser.add_argument("--jenkins-cluster-name", dest="jenkins/cluster-name", metavar="NAME", help="Jenkins: name of the cluster in the cloud configuration")
    parser.add_argument("--jenkins-capacity", dest="jenkins/capacity", type=int, metavar="NUM", help="Jenkins: beginning value of the cluster capacity")
    parser.add_argument("--create-pods", dest="create/pods", type=float, metavar="0<NUM<1", help="Create new node threshold: num of pods per node")
    parser.add_argument("--delete-pods", dest="delete/pods", type=float, metavar="0<NUM<1", help="Delete node threshold: num of pods per node")
    parser.add_argument("--create-cpu", dest="create/cpu", type=float, metavar="0<NUM<1", help="Create new node threshold: CPU limit per CPUs in cluster")
    parser.add_argument("--delete-cpu", dest="delete/cpu", type=float, metavar="0<NUM<1", help="Delete node threshold: CPU limit per CPUs in cluster")
    parser.add_argument("--create-memory", dest="create/memory", type=float, metavar="0<NUM<1", help="Create new node threshold: CPU limit per CPUs in cluster")
    parser.add_argument("--delete-memory", dest="delete/memory", type=float, metavar="0<NUM<1", help="Delete node threshold: CPU limit per CPUs in cluster")
    parser.add_argument("--delay-create", dest="delay/create", type=int, default=0, metavar="SEC", help="Create new node only if threshold overcome for a number of seconds")
    parser.add_argument("--delay-delete", dest="delay/delete", type=int, default=600, metavar="SEC", help="Delete if the parameter is below the threshold for a number of seconds")
    parser.add_argument("--override-pods-max", dest="override/pods_max", type=int, metavar="NUM", help="Override pods maximum per node")
    parser.add_argument("--sleep-time", dest="sleep-time", type=int, default=10, metavar="SEC", help="Timeout between update cycle")
    parser.add_argument("--report-ignore-namespaces", dest="report/ignore-namespaces", default="kube-system", metavar="N(,N...)", help="Report: comma-separated ignoring namespaces")
    options = vars(parser.parse_args())

    try:
        japi = JenkinsApi(Request(
            api_url  = options['jenkins/url'],
            user     = options['jenkins/user'],
            password = options['jenkins/token']
        )) if options['jenkins/url'] else None

        autoscaler = Autoscaler(options, KubernetesApi(Request(
            api_url  = options['kubernetes/api-url'],
            user     = options['kubernetes/user'],
            password = options['kubernetes/token'])), jenkins_obj = japi)
    except Exception as e:
        parser.error(str(e))

    autoscaler.run()
