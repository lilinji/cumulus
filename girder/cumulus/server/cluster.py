import cherrypy
import json
import re

from girder.api.rest import Resource
from girder.api import access
from girder.api.describe import Description
from girder.constants import AccessType
from girder.api.docs import addModel

from cumulus.starcluster.tasks import start_cluster, terminate_cluster, submit_job


class Cluster(Resource):

    def __init__(self):
        self.resourceName = 'clusters'
        self.route('POST', (), self.create)
        self.route('POST', (':id', 'log'), self.handle_log_record)
        self.route('GET', (':id', 'log'), self.log)
        self.route('PUT', (':id', 'start'), self.start)
        self.route('PATCH', (':id',), self.update)
        self.route('GET', (':id', 'status'), self.status)
        self.route('PUT', (':id', 'terminate'), self.terminate)
        self.route('PUT', (':id', 'job', ':jobId', 'submit'), self.submit_job)

        # TODO Findout how to get plugin name rather than hardcoding it
        self._model = self.model('cluster', 'cumulus')

    @access.user
    def handle_log_record(self, id, params):
        user = self.getCurrentUser()
        return self._model.add_log_record(user, id, json.load(cherrypy.request.body))

    @access.user
    def create(self, params):
        name = params['name']
        template = params['template']
        config_id = params['configId']

        user = self.getCurrentUser()

        return {'id': self._model.create(user, config_id, name, template)}

    create.description = (Description(
            'Create a cluster'
        )
        .param(
            'name',
            'The name to give the cluster.',
            required=True, paramType='query')
        .param(
            'template',
            'The cluster template to use'+
            '(default="(empty)")',
            required=True, paramType='query')
        .param(
            'configId',
            'The starcluster config to use when creating',
            required=True, paramType='query'))

    @access.user
    def start(self, id, params):

        log_write_url = cherrypy.url().replace('start', 'log')
        base_url = re.match('(.*)/clusters.*', cherrypy.url()).group(1)
        status_url = '%s/clusters/%s' % (base_url, id)

        (user, token) = self.getCurrentUser(returnToken=True)
        cluster = self._model.load(id, user=user, level=AccessType.ADMIN)

        # Need to replace config id
        config_url = '%s/starcluster-configs/%s?format=ini' % (base_url, cluster['configId'])

        start_cluster.delay(cluster['name'], cluster['template'],
                            log_write_url=log_write_url, status_url=status_url,
                            config_url=config_url, girder_token=token['_id'])

    start.description = (Description(
            'Start a cluster'
        )
        .param(
            'id',
            'The cluster id to start.', paramType='path'))

    @access.user
    def update(self, id, params):
        body = json.loads(cherrypy.request.body.read())
        user = self.getCurrentUser()

        if 'status' in body:
            status = body['status']

        cluster = self._model.update_cluster(user, id, status)

        # Don't return the access object
        del cluster['access']
        # Don't return the log
        del cluster['log']

        return cluster

    addModel("ClusterUpdateParameters", {
        "id":"ClusterUpdateParameters",
        "properties":{
            "status": {"type": "string", "description": "The new status. (optional)"}
        }
    })


    update.description = (Description(
            'Update the cluster'
        )
        .param('id',
              'The id of the cluster to update', paramType='path')
        .param(
            'body',
            'The properties to update.', dataType='ClusterUpdateParameters' , paramType='body'))

    @access.user
    def status(self, id, params):
        user = self.getCurrentUser()
        status = self._model.status(user, id)

        return {'status': status}

    status.description = (Description(
            'Get the clusters current state'
        )
        .param(
            'id',
            'The cluster id to get the status of.', paramType='path'))

    @access.user
    def terminate(self, id, params):

        log_write_url = cherrypy.url().replace('terminate', 'log')
        status_url = cherrypy.url().replace('terminate', 'status')
        config_url = re.match('(.*)/clusters.*', cherrypy.url()).group(1)
        config_url += '/starcluster-configs/%s?format=ini'

        (user, token) = self.getCurrentUser(returnToken=True)
        cluster = self._model.load(id, user=user, level=AccessType.ADMIN)

        config_url = config_url % cluster['configId']

        terminate_cluster.delay(cluster['name'],
                            log_write_url=log_write_url, status_url=status_url,
                            config_url=config_url, girder_token=token['_id'])

    terminate.description = (Description(
            'Terminate a cluster'
        )
        .param(
            'id',
            'The cluster to terminate.', paramType='path'))

    @access.user
    def log(self, id, params):
        user = self.getCurrentUser()
        offset = 0
        if 'offset' in params:
            offset = int(params['offset'])

        log_records = self._model.log_records(user, id, offset)

        return {'log': log_records}

    log.description = (Description(
            'Get log entries for cluster'
        )
        .param(
            'id',
            'The cluster to get log entries for.', paramType='path')
        .param(
            'offset',
            'The cluster to get log entries for.', required=False, paramType='query'))

    @access.user
    def submit_job(self, id, jobId, params):
        job_id = jobId
        (user, token) = self.getCurrentUser(returnToken=True)
        cluster = self._model.load(id, user=user, level=AccessType.ADMIN)

        base_url = re.match('(.*)/clusters.*', cherrypy.url()).group(1)
        config_url = '%s/starcluster-configs/%s?format=ini' % (base_url, cluster['configId'])

        job = self.model('job', 'cumulus').load(job_id, user=user, level=AccessType.ADMIN)
        log_url = '%s/jobs/%s/log' % (base_url, job_id)
        job['_id'] = str(job['_id'])
        del job['access']

        submit_job.delay(cluster['name'], job,
                            log_write_url=log_url,  config_url= config_url,
                            girder_token=token['_id'],
                            base_url=base_url)

    submit_job.description = (Description(
            'Submit a job to the cluster'
        )
        .param(
            'id',
            'The cluster to submit the job to.', required=True, paramType='path')
        .param(
            'jobId',
            'The cluster to get log entries for.', required=True, paramType='path'))
#    @access.public
#    def config(self, id):
#        pass

#    config.description = (Description(
#            'Get StarCluster configuration for this cluster'
#        )
#        .param(
#            'id',
#            'The cluster to get configuration for.', paramType='path'))



