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
	""" Mocks endpoint HTTP calls returning values in order. """

	def urlopen(request):
		return Response(values.pop(0))

	monkeypatch.setattr(remote_endpoint_module.urllib.request, 'urlopen', urlopen)
	monkeypatch.setattr(remote_endpoint_module.json, 'load', lambda response: response.value)


def test_remote_endpoint_capabilities_and_functions(monkeypatch):
	""" Builds functions from remote capabilities without connecting. """

	_mock_responses(monkeypatch, [{'capabilities': [_capability()]}])
	endpoint = RemoteEndpoint('http://endpoint')

	assert endpoint.functions == {'answer': {'dsc': 'Answers a question.', 'args': {'question': {'typ': 'string', 'dsc': 'The question.', 'req': True}}}}

	endpoint = RemoteEndpoint.__new__(RemoteEndpoint)
	endpoint.base_url = 'http://endpoint'
	_mock_responses(monkeypatch, [{}])
	with pytest.raises(RuntimeError):
		endpoint.get_capabilities()

	endpoint.capabilities = [_capability()]
	assert endpoint.get_functions()['answer']['args']['question']['req'] is True


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


def test_remote_endpoint_dry_run(monkeypatch):
	""" Sends dry-run requests and returns the remote response. """

	result = {'status': 0, 'description': 'Valid request.'}
	_mock_responses(monkeypatch, [{'capabilities': [_capability()]}, result])
	endpoint = RemoteEndpoint('http://endpoint')

	assert endpoint.dry_run('answer', {'question': 'question'}) == result
