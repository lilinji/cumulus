from tests import base
import json
import httmock
import mock
import re
from jsonschema import validate


def setUpModule():
    base.enabledPlugins.append('task')
    base.startServer()


def tearDownModule():
    base.stopServer()


class TaskTestCase(base.TestCase):

    def _normalize(self, data):
        str_data = json.dumps(data, default=str)
        str_data = re.sub(r'[\w]{64}', 'token', str_data)
        str_data = re.sub(r'[\w]{24}', 'id', str_data)

        return json.loads(str_data)

    def assertCalls(self, actual, expected, msg=None):
        calls = []
        for (args, kwargs) in self._normalize(actual):
            calls.append((args, kwargs))

        self.assertListEqual(self._normalize(calls), expected, msg)

    def _create_spec(self, path):
        with open(path) as fp:
            spec = fp.read()

        # Create task spec
        resp = self.request(
            path='/file', method='POST', user=self._user, params={
                'parentType': 'folder',
                'parentId': self.privateFolder['_id'],
                'name': 'spec',
                'size': len(spec),
                'mimeType': 'text/plain'
            })
        self.assertStatusOk(resp)

        uploadId = resp.json['_id']

        # Uploading with no user should fail
        fields = [('offset', 0), ('uploadId', uploadId)]
        files = [('chunk', 'helloWorld.txt', spec)]
        resp = self.multipartRequest(
            path='/file/chunk', fields=fields, files=files, user=self._user)
        self.assertStatusOk(resp)

        return resp.json['_id']

    def setUp(self):
        super(TaskTestCase, self).setUp()

        users = ({
            'email': 'cumulus@email.com',
            'login': 'cumulus',
            'firstName': 'First',
            'lastName': 'Last',
            'password': 'goodpassword'
        }, {
            'email': 'regularuser@email.com',
            'login': 'regularuser',
            'firstName': 'First',
            'lastName': 'Last',
            'password': 'goodpassword'
        })
        self._cumulus, self._user = \
            [self.model('user').createUser(**user) for user in users]

        self._group = self.model('group').createGroup('cumulus', self._cumulus)

        folders = self.model('folder').childFolders(
            parent=self._user, parentType='user', user=self._user)
        for folder in folders:
            if folder['public'] is True:
                self.publicFolder = folder
            else:
                self.privateFolder = folder

        self._simpleSpecId = self._create_spec(
            'plugins/task/plugin_tests/fixtures/simple.json')
        self._complexSpecId = self._create_spec(
            'plugins/task/plugin_tests/fixtures/complex.json')
        self._mesh_called = False
        self._cluster_created = False
        self._cluster_started = False
        self._job_submitted = False

    def test_schema(self):
        with open('plugins/task/task.json', 'r') as fp:
            schema = json.load(fp)

        with open('plugins/task/plugin_tests/fixtures/simple.json', 'r') as fp:
            test = json.load(fp)
            validate(test, schema)

        with open('plugins/task/plugin_tests/fixtures/complex.json', 'r') as fp:
            test = json.load(fp)
            validate(test, schema)

    def test_create(self):
        body = {
            'taskSpecId': self._simpleSpecId,
        }
        body = json.dumps(body)

        r = self.request('/tasks', method='POST',
                         type='application/json', body=body, user=self._user)
        self.assertStatus(r, 201)
        self.assertEquals(r.json['taskSpecId'], self._simpleSpecId)

    def run_simple(self):
        body = {
            'taskSpecId': self._simpleSpecId,
        }
        body = json.dumps(body)
        r = self.request('/tasks', method='POST',
                         type='application/json', body=body, user=self._user)
        self.assertStatus(r, 201)
        self.assertEquals(r.json['taskSpecId'], self._simpleSpecId)
        task_id = r.json['_id']

        mesh_id = 'asdklasjdlf;kasjdklf'
        body = {
            'mesh': {
                'id': mesh_id
            },
            'output': {
                'itemId': 'itemId',
                'name': 'name'
            }
        }
        body = json.dumps(body)
        url = '/tasks/%s/run' % str(task_id)

        def _mesh_mock(url, request):
            headers = {
                'content-length': 0
            }

            self.assertEquals(url.path.split('/')[4], mesh_id)
            self._mesh_called = True
            return httmock.response(200, None, headers, request=request)

        mesh_mock = httmock.urlmatch(
            path=r'^/api/v1/meshes/.*/extract/surface$')(_mesh_mock)

        with httmock.HTTMock(mesh_mock):
            r = self.request(url, method='PUT',
                             type='application/json', body=body, user=self._user)
        self.assertStatusOk(r)
        self.assertTrue(self._mesh_called)

    @mock.patch('cumulus.task.runner.app.send_task')
    def test_run_complex(self, monitor_status):
        body = {
            'taskSpecId': self._complexSpecId,
        }
        body = json.dumps(body)
        r = self.request('/tasks', method='POST',
                         type='application/json', body=body, user=self._user)
        self.assertStatus(r, 201)
        self.assertEquals(r.json['taskSpecId'], self._complexSpecId)
        task_id = r.json['_id']

        config_id = 'asdklasjdlf;kasjdklf'
        job_id = 'asdklasjdlf;kasjdklf'
        body = {
            'config': {
                'id': config_id
            },
            'job': {
                'id': job_id
            },
            'output': {
                'item': {
                    'id': 'item_id'
                }
            },
            'input': {
                'item': {
                    'id': 'item_id'
                }
            }
        }
        body = json.dumps(body)
        url = '/tasks/%s/run' % str(task_id)

        cluster_id = 'cluster_id'

        def _create_cluster(url, request):
            content = {
                "_id": cluster_id
            }
            content = json.dumps(content)
            headers = {
                'content-length': len(content),
                'content-type': 'application/json'
            }

            self._cluster_created = True
            return httmock.response(200, content, headers, request=request)

        create_cluster = httmock.urlmatch(
            path=r'^/api/v1/clusters$', method='POST')(_create_cluster)

        def _start_cluster(url, request):

            headers = {
                'content-length': 0,
                'content-type': 'application/json'
            }

            self._cluster_started = True
            return httmock.response(200, None, headers, request=request)

        start_cluster = httmock.urlmatch(
            path=r'^/api/v1/clusters/%s/start$' % cluster_id, method='PUT')(_start_cluster)

        def _create_job(url, request):
            content = {
                '_id': job_id,
            }
            content = json.dumps(content)
            headers = {
                'content-length': len(content),
                'content-type': 'application/json'
            }

            self._job_submitted = True
            return httmock.response(200, content, headers, request=request)

        create_job = httmock.urlmatch(
            path=r'^/api/v1/jobs$', method='POST')(_create_job)

        def _submit_job(url, request):

            headers = {
                'content-length': 0,
                'content-type': 'application/json'
            }

            self._job_submitted = True
            return httmock.response(200, None, headers, request=request)

        submit_job = httmock.urlmatch(
            path=r'^/api/v1/clusters/%s/submit/job/%s$' % (cluster_id, job_id), method='PUT')(_submit_job)

        with httmock.HTTMock(create_cluster, start_cluster, create_job, submit_job):
            r = self.request(url, method='PUT',
                             type='application/json', body=body, user=self._user)
        self.assertStatusOk(r)
        self.assertTrue(self._cluster_created)
        self.assertTrue(self._cluster_started)
        self.assertTrue(self._job_submitted)

        expected_calls = [[[u'cumulus.task.status.monitor_status'], {u'args': [u'token', {u'_id': u'id', u'taskSpecId': u'id'}, {u'steps': [{u'type': u'http', u'params': {u'url': u'/clusters', u'output': u'cluster', u'body': {u'config': [{u'_id': u'{{config.id}}'}], u'name': u'test_cluster', u'template': u'default_cluster'}, u'method': u'POST'}, u'name': u'createcluster'}, {u'body': {}, u'type': u'http', u'params': {u'url': u'/clusters/{{cluster._id}}/start', u'method': u'PUT'}, u'name': u'start cluster'}, {u'type': u'status', u'params': {u'url': u'/clusters/{{cluster._id}}/status', u'failure': [u'error'], u'success': [u'running'], u'selector': u'status'}, u'name': u'Wait for cluster'}, {u'type': u'http', u'params': {u'url': u'/jobs', u'body': {u'output': {u'itemId': u'{{output.item.id}}'}, u'scriptId': u'script_id', u'name': u'myjob', u'input': [{u'itemId': u'{{input.item.id}}', u'path': u'{{input.path}}'}]}, u'method': u'POST', u'output': u'job'}, u'name': u'create job'}, {u'type': u'http', u'params': {u'url': u'/clusters/{{cluster._id}}/submit/job/{{job._id}}', u'method': u'PUT'}, u'name': u'submit job'}, {u'type': u'status', u'params': {u'url': u'/clusters/{{cluster._id}}/status', u'failure': [u'error'], u'success': [u'complete', u'terminated'], u'selector': u'status'}, u'name': u'Wait for job to complete'}], u'name': u'Run cluster job'}, 2, {u'cluster': {u'_id': u'cluster_id'}, u'job': {u'_id': u'asdklasjdlf;kasjdklf'}, u'config': {u'id': u'asdklasjdlf;kasjdklf'}, u'input': {u'item': {u'id': u'item_id'}}, u'output': {u'item': {u'id': u'item_id'}}}]}], [
            [u'cumulus.task.status.monitor_status'], {u'args': [u'token', {u'_id': u'id', u'taskSpecId': u'id'}, {u'steps': [{u'type': u'http', u'params': {u'url': u'/clusters', u'output': u'cluster', u'body': {u'config': [{u'_id': u'{{config.id}}'}], u'name': u'test_cluster', u'template': u'default_cluster'}, u'method': u'POST'}, u'name': u'createcluster'}, {u'body': {}, u'type': u'http', u'params': {u'url': u'/clusters/{{cluster._id}}/start', u'method': u'PUT'}, u'name': u'start cluster'}, {u'type': u'status', u'params': {u'url': u'/clusters/{{cluster._id}}/status', u'failure': [u'error'], u'success': [u'running'], u'selector': u'status'}, u'name': u'Wait for cluster'}, {u'type': u'http', u'params': {u'url': u'/jobs', u'body': {u'output': {u'itemId': u'{{output.item.id}}'}, u'scriptId': u'script_id', u'name': u'myjob', u'input': [{u'itemId': u'{{input.item.id}}', u'path': u'{{input.path}}'}]}, u'method': u'POST', u'output': u'job'}, u'name': u'create job'}, {u'type': u'http', u'params': {u'url': u'/clusters/{{cluster._id}}/submit/job/{{job._id}}', u'method': u'PUT'}, u'name': u'submit job'}, {u'type': u'status', u'params': {u'url': u'/clusters/{{cluster._id}}/status', u'failure': [u'error'], u'success': [u'complete', u'terminated'], u'selector': u'status'}, u'name': u'Wait for job to complete'}], u'name': u'Run cluster job'}, 5, {u'cluster': {u'_id': u'cluster_id'}, u'job': {u'_id': u'asdklasjdlf;kasjdklf'}, u'config': {u'id': u'asdklasjdlf;kasjdklf'}, u'input': {u'item': {u'id': u'item_id'}}, u'output': {u'item': {u'id': u'item_id'}}}]}]]

        self.assertCalls(monitor_status.call_args_list, expected_calls)