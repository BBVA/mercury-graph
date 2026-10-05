import json

import pytest

from mercury.graph.evidence.remote import RemoteEndpoint

import mercury.graph.evidence.remote.remote_endpoint as remote_endpoint_module


class Response:
	""" Provides a context-managed mocked HTTP response. """

	def __init__(self, value):
		""" Stores JSON-decoded response value. """

		self.value = value


	def __enter__(self):
		""" Returns this response from a context manager. """

		return self


	def __exit__(self, exception_type, exception_value, traceback):
		""" Closes the mocked response context. """


def _capability():
	""" Returns a valid single string-argument capability. """

	return {
		'type': 'function',
		'function': {
			'name': 'answer',
			'description': 'Answers a question.',
			'parameters': {
				'type': 'object',
				'required': ['question'],
				'properties': {'question': {'type': 'string', 'description': 'The question.'}}
			}
		}
	}


def _mock_responses(monkeypatch, values):
	""" Mocks endpoint HTTP calls returning values in order. Returns the list where the requests are recorded. """

	requests = []

	def urlopen(request):
		requests.append(request)
		return Response(values.pop(0))

	monkeypatch.setattr(remote_endpoint_module.urllib.request, 'urlopen', urlopen)
	monkeypatch.setattr(remote_endpoint_module.json, 'load', lambda response: response.value)

	return requests


def test_remote_endpoint_capabilities(monkeypatch):
	""" Lists and describes remote capabilities without connecting. """

	search = _capability()
	search['function']['name'] = 'search'
	search['function']['parameters']['properties']['limit'] = {'type': 'integer'}

	_mock_responses(monkeypatch, [{'capabilities': [_capability(), search]}])
	endpoint = RemoteEndpoint('http://endpoint')

	assert endpoint.capabilities == [_capability(), search]
	assert endpoint.list_capabilities() == ['answer', 'search']

	assert endpoint.describe('answer') == {
		'name': 'answer',
		'description': 'Answers a question.',
		'arguments': {'question': {'type': 'string', 'description': 'The question.', 'required': True}}
	}
	assert endpoint.describe('search')['arguments']['limit'] == {'type': 'integer', 'description': '', 'required': False}

	endpoint.describe('answer')['arguments']['question']['required'] = False
	assert endpoint.describe('answer')['arguments']['question']['required'] is True

	with pytest.raises(KeyError):
		endpoint.describe('unknown')

	endpoint = RemoteEndpoint.__new__(RemoteEndpoint)
	endpoint.base_url = 'http://endpoint'
	_mock_responses(monkeypatch, [{}])
	with pytest.raises(RuntimeError):
		endpoint.get_capabilities()


def test_remote_endpoint_run(monkeypatch):
	""" Runs remote functions and simplifies successful responses. """

	_mock_responses(monkeypatch, [
		{'capabilities': [_capability()]},
		{'finish_reason': 'stop', 'message': {'content': 'answer'}},
		{'finish_reason': 'stop', 'message': 'plain answer'},
		{'finish_reason': 'stop', 'message': {'content': 'with history'}, 'history': []}
	])
	endpoint = RemoteEndpoint('http://endpoint')

	assert endpoint.run('answer', 'question') == 'answer'
	assert endpoint.run('answer', {}) == 'plain answer'
	assert endpoint.run('answer', {}, easy = False) == {'finish_reason': 'stop', 'message': {'content': 'with history'}, 'history': []}


def test_remote_endpoint_run_request(monkeypatch):
	""" Sends the capability name and its arguments, wrapping a string into the only argument when easy. """

	stop = {'finish_reason': 'stop', 'message': 'answer'}
	requests = _mock_responses(monkeypatch, [{'capabilities': [_capability()]}, stop, stop, stop])
	endpoint = RemoteEndpoint('http://endpoint')

	endpoint.run('answer', 'question')
	endpoint.run('answer', {'question': 'question'})
	endpoint.run('answer', 'question', easy = False)

	assert [request.full_url for request in requests[1:]] == ['http://endpoint/run'] * 3
	assert [json.loads(request.data) for request in requests[1:]] == [
		{'name': 'answer', 'arguments': {'question': 'question'}},
		{'name': 'answer', 'arguments': {'question': 'question'}},
		{'name': 'answer', 'arguments': 'question'}
	]


def test_remote_endpoint_dry_run(monkeypatch):
	""" Sends dry-run requests and returns the remote response. """

	result = {'status': 0, 'description': 'Valid request.'}
	_mock_responses(monkeypatch, [{'capabilities': [_capability()]}, result])
	endpoint = RemoteEndpoint('http://endpoint')

	assert endpoint.dry_run('answer', {'question': 'question'}) == result
