import json
import urllib.error

import pytest

from mercury.graph.evidence.remote import RemoteEndpoint, RemoteEndpointError

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


def _capability_with(name, properties, required):
	""" Returns a capability with the given name, argument properties and required argument names. """

	capability = _capability()
	capability['function']['name'] = name
	capability['function']['parameters']['properties'] = properties
	capability['function']['parameters']['required'] = required

	return capability


def _mock_responses(monkeypatch, values):
	""" Mocks endpoint HTTP calls returning values in order, or raising them if they are exceptions. Returns the list where the
	requests are recorded.
	"""

	requests = []

	def urlopen(request):
		requests.append(request)
		value = values.pop(0)
		if isinstance(value, Exception):
			raise value

		return Response(value)

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


def test_remote_endpoint_run_text_arguments(monkeypatch):
	""" Wraps a text into the only required string argument, or the only argument, and fails before sending it otherwise. """

	search = _capability_with('search', {'question': {'type': 'string'}, 'limit': {'type': 'integer'}}, ['question'])
	echo   = _capability_with('echo', {'text': {'type': 'string'}}, [])
	count  = _capability_with('count', {'limit': {'type': 'integer'}}, ['limit'])
	pair   = _capability_with('pair', {'a': {'type': 'string'}, 'b': {'type': 'string'}}, ['a', 'b'])
	maybe  = _capability_with('maybe', {'a': {'type': 'string'}, 'b': {'type': 'string'}}, [])
	ping   = _capability_with('ping', {}, [])

	stop = {'finish_reason': 'stop', 'message': 'answer'}
	requests = _mock_responses(monkeypatch, [{'capabilities': [search, echo, count, pair, maybe, ping]}, stop, stop])
	endpoint = RemoteEndpoint('http://endpoint')

	endpoint.run('search', 'question')
	endpoint.run('echo', 'hello')

	assert [json.loads(request.data) for request in requests[1:]] == [
		{'name': 'search', 'arguments': {'question': 'question'}},
		{'name': 'echo', 'arguments': {'text': 'hello'}}
	]

	with pytest.raises(RemoteEndpointError, match = '"count" takes its argument "limit" as integer, not as text'):
		endpoint.run('count', 'ten')

	with pytest.raises(RemoteEndpointError, match = '"pair" takes 2 required arguments but only one text was given.*: a, b'):
		endpoint.run('pair', 'text')

	with pytest.raises(RemoteEndpointError, match = '"maybe" takes 2 optional arguments but only one text was given'):
		endpoint.run('maybe', 'text')

	with pytest.raises(RemoteEndpointError, match = r'"ping" takes no arguments\. Pass an empty dictionary: \{\}\.'):
		endpoint.run('ping', 'text')

	assert len(requests) == 3


def test_remote_endpoint_run_last_response(monkeypatch):
	""" Keeps the complete response in last_response, returns the content of an agent with history and raises on errors. """

	answer = {'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'Elena Ruiz.'}, 'history': [{'role': 'user'}]}
	error  = {'finish_reason': 'error', 'message': {'role': 'assistant', 'content': 'The tool failed.'}, 'history': [{'role': 'user'}]}

	_mock_responses(monkeypatch, [{'capabilities': [_capability()]}, answer, error, error])
	endpoint = RemoteEndpoint('http://endpoint')

	assert endpoint.last_response is None

	assert endpoint.run('answer', 'Who teaches?') == 'Elena Ruiz.'
	assert endpoint.last_response == answer

	with pytest.raises(RemoteEndpointError, match = 'The tool failed.'):
		endpoint.run('answer', 'Who teaches?')
	assert endpoint.last_response == error

	assert endpoint.run('answer', {'question': 'Who teaches?'}, easy = False) == error
	assert endpoint.last_response == error


def test_remote_endpoint_run_resets_last_response(monkeypatch):
	""" Leaves last_response empty when a call does not get a response. """

	stop = {'finish_reason': 'stop', 'message': 'answer'}
	_mock_responses(monkeypatch, [{'capabilities': [_capability()]}, stop, urllib.error.URLError('refused')])
	endpoint = RemoteEndpoint('http://endpoint')

	endpoint.run('answer', 'question')
	assert endpoint.last_response == stop

	with pytest.raises(urllib.error.URLError):
		endpoint.run('answer', 'question')
	assert endpoint.last_response is None


def test_remote_endpoint_dry_run(monkeypatch):
	""" Sends dry-run requests and returns the remote response. """

	result = {'status': 0, 'description': 'Valid request.'}
	_mock_responses(monkeypatch, [{'capabilities': [_capability()]}, result])
	endpoint = RemoteEndpoint('http://endpoint')

	assert endpoint.dry_run('answer', {'question': 'question'}) == result
