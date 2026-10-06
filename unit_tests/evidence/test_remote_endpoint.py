import io
import json
import re
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


def _capabilities():
	""" Returns capabilities covering the different argument layouts. """

	return [
		_capability(),
		_capability_with('search', {'text': {'type': 'string'}, 'concepts': {'type': 'array'}}, ['text']),
		_capability_with('echo', {'text': {'type': 'string'}}, []),
		_capability_with('count', {'limit': {'type': 'integer'}}, ['limit']),
		_capability_with('pair', {'a': {'type': 'string'}, 'b': {'type': 'string'}}, ['a', 'b']),
		_capability_with('maybe', {'a': {'type': 'string'}, 'b': {'type': 'string'}}, []),
		_capability_with('ping', {}, []),
		_capability_with('chat_with_reader', {'content': {'type': 'string'}}, ['content'])
	]


def _stop(message = 'answer'):
	""" Returns a successful response with the given message. """

	return {'finish_reason': 'stop', 'message': message}


def _http_error(body):
	""" Returns an HTTP 500 error with the given body. """

	return urllib.error.HTTPError('http://endpoint/run', 500, 'Internal Server Error', {}, io.BytesIO(body))


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


def _endpoint(monkeypatch, *responses, capabilities = None):
	""" Creates a RemoteEndpoint with the given capabilities (all of `_capabilities()` by default) and mocks the responses to its
	later calls. Returns the endpoint and the list where those later requests are recorded.
	"""

	if capabilities is None:
		capabilities = _capabilities()

	requests = _mock_responses(monkeypatch, [{'capabilities': capabilities}] + list(responses))
	endpoint = RemoteEndpoint('http://endpoint')

	requests.clear()

	return endpoint, requests


# Capabilities

def test_remote_endpoint_keeps_capabilities(monkeypatch):
	""" Keeps the capabilities as given by the Endpoint metadata. """

	endpoint, _ = _endpoint(monkeypatch)

	assert endpoint.capabilities == _capabilities()


def test_remote_endpoint_list_capabilities(monkeypatch):
	""" Lists the capability names in the order given by the Endpoint. """

	endpoint, _ = _endpoint(monkeypatch)

	assert endpoint.list_capabilities() == ['answer', 'search', 'echo', 'count', 'pair', 'maybe', 'ping', 'chat_with_reader']


def test_remote_endpoint_describe(monkeypatch):
	""" Describes a capability with its required and optional arguments. """

	endpoint, _ = _endpoint(monkeypatch)

	assert endpoint.describe('search') == {
		'name': 'search',
		'description': 'Answers a question.',
		'arguments': {
			'text': {'type': 'string', 'description': '', 'required': True},
			'concepts': {'type': 'array', 'description': '', 'required': False}
		}
	}


def test_remote_endpoint_describe_returns_a_copy(monkeypatch):
	""" Returns a description that can be modified without changing the endpoint. """

	endpoint, _ = _endpoint(monkeypatch)

	endpoint.describe('answer')['arguments']['question']['required'] = False

	assert endpoint.describe('answer')['arguments']['question']['required'] is True


def test_remote_endpoint_without_capabilities(monkeypatch):
	""" Fails when the Endpoint metadata has no capabilities. """

	_mock_responses(monkeypatch, [{}])

	with pytest.raises(RemoteEndpointError, match = 'does not expose capabilities'):
		RemoteEndpoint('http://endpoint')


# Running a capability

def test_remote_endpoint_run_sends_request(monkeypatch):
	""" Sends the capability name and its arguments to the run path. """

	endpoint, requests = _endpoint(monkeypatch, _stop())

	endpoint.run('answer', {'question': 'question'})

	assert requests[0].full_url == 'http://endpoint/run'
	assert json.loads(requests[0].data) == {'name': 'answer', 'arguments': {'question': 'question'}}


def test_remote_endpoint_run_returns_message(monkeypatch):
	""" Returns the message of the response. """

	endpoint, _ = _endpoint(monkeypatch, _stop(['a', 'b']))

	assert endpoint.run('answer', 'question') == ['a', 'b']


def test_remote_endpoint_run_returns_agent_content(monkeypatch):
	""" Returns the content of an agent's message. """

	endpoint, _ = _endpoint(monkeypatch, _stop({'role': 'assistant', 'content': 'Elena Ruiz.'}))

	assert endpoint.run('chat_with_reader', 'question') == 'Elena Ruiz.'


def test_remote_endpoint_run_keeps_message_of_other_capabilities(monkeypatch):
	""" Returns the whole message of a capability that is not an agent's, even if it looks like an agent's message. """

	message = {'role': 'assistant', 'content': 'Elena Ruiz.'}
	endpoint, _ = _endpoint(monkeypatch, _stop(message))

	assert endpoint.run('answer', 'question') == message


def test_remote_endpoint_run_keeps_object_with_content(monkeypatch):
	""" Returns a whole object that has a content but is not a chat message, such as a Source leaf. """

	leaf = {'type': 'SourceEntity: SourceEntityType.TEXT', 'content': 'Noah Kim studies at Riverside High School.'}
	endpoint, _ = _endpoint(monkeypatch, _stop(leaf))

	assert endpoint.run('answer', 'question') == leaf


def test_remote_endpoint_run_returns_agent_content_with_history(monkeypatch):
	""" Returns the content of an agent's message also when the response includes its history. """

	response = {'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'Elena Ruiz.'}, 'history': [{'role': 'user'}]}
	endpoint, _ = _endpoint(monkeypatch, response)

	assert endpoint.run('chat_with_reader', 'question') == 'Elena Ruiz.'


def test_remote_endpoint_run_raises_on_error_finish(monkeypatch):
	""" Raises with the message of a response that finishes with an error. """

	endpoint, _ = _endpoint(monkeypatch, {'finish_reason': 'error', 'message': {'role': 'assistant', 'content': 'The tool failed.'}})

	with pytest.raises(RemoteEndpointError, match = re.escape('"answer" finished with an error: The tool failed.')):
		endpoint.run('answer', 'question')


def test_remote_endpoint_run_not_easy_returns_response(monkeypatch):
	""" Returns the complete response when easy is False, also when it finishes with an error. """

	response = {'finish_reason': 'error', 'message': 'The tool failed.', 'history': []}
	endpoint, _ = _endpoint(monkeypatch, response)

	assert endpoint.run('answer', {'question': 'question'}, easy = False) == response


# Passing a text as the arguments

@pytest.mark.parametrize('name, arguments', [
	('answer', {'question': 'text'}),
	('search', {'text': 'text'}),
	('echo', {'text': 'text'})
], ids = ['only required', 'required with optional', 'only optional'])
def test_remote_endpoint_run_wraps_text(monkeypatch, name, arguments):
	""" Passes a text as the only required string argument, or as the only argument if none is required. """

	endpoint, requests = _endpoint(monkeypatch, _stop())

	endpoint.run(name, 'text')

	assert json.loads(requests[0].data)['arguments'] == arguments


@pytest.mark.parametrize('name, message', [
	('count', '"count" takes its argument "limit" as integer, not as text. Pass a dictionary with its arguments: limit.'),
	('pair', '"pair" takes 2 required arguments but only one text was given. Pass a dictionary with its arguments: a, b.'),
	('maybe', '"maybe" takes 2 optional arguments but only one text was given. Pass a dictionary with its arguments: a, b.'),
	('ping', '"ping" takes no arguments. Pass an empty dictionary: {}.')
], ids = ['not a string', 'several required', 'several optional', 'no arguments'])
def test_remote_endpoint_run_rejects_text(monkeypatch, name, message):
	""" Explains why a text cannot be the arguments, before sending anything. """

	endpoint, requests = _endpoint(monkeypatch)

	with pytest.raises(RemoteEndpointError, match = re.escape(message)):
		endpoint.run(name, 'text')

	assert requests == []


def test_remote_endpoint_run_does_not_wrap_text_when_not_easy(monkeypatch):
	""" Rejects a text as the arguments when easy is False, before sending anything. """

	endpoint, requests = _endpoint(monkeypatch)

	with pytest.raises(RemoteEndpointError, match = 'takes its arguments as a dictionary, not as str'):
		endpoint.run('answer', 'question', easy = False)

	assert requests == []


# Checking the arguments

@pytest.mark.parametrize('name, arguments, message', [
	('search', {'txt': 'x'}, '"search" has no argument "txt" and is missing its required argument "text". Its arguments are: text, concepts.'),
	('search', {'concepts': []}, '"search" is missing its required argument "text". Its arguments are: text, concepts.'),
	('pair', {}, '"pair" is missing its required arguments "a", "b". Its arguments are: a, b.'),
	('pair', {'a': '1', 'b': '2', 'c': '3', 'd': '4'}, '"pair" has no arguments "c", "d". Its arguments are: a, b.'),
	('ping', [], '"ping" takes its arguments as a dictionary, not as list. It takes no arguments: pass {}.')
], ids = ['unknown and missing', 'missing', 'several missing', 'several unknown', 'not a dictionary'])
def test_remote_endpoint_run_checks_arguments(monkeypatch, name, arguments, message):
	""" Rejects arguments that are not a dictionary, unknown or missing, before sending anything. """

	endpoint, requests = _endpoint(monkeypatch)

	with pytest.raises(RemoteEndpointError, match = re.escape(message)):
		endpoint.run(name, arguments)

	assert requests == []


@pytest.mark.parametrize('call', [
	lambda endpoint: endpoint.run('anwser', 'question'),
	lambda endpoint: endpoint.dry_run('anwser', {'question': 'question'}),
	lambda endpoint: endpoint.describe('anwser')
], ids = ['run', 'dry_run', 'describe'])
def test_remote_endpoint_rejects_unknown_capability(monkeypatch, call):
	""" Rejects an unknown capability, before sending anything. """

	endpoint, requests = _endpoint(monkeypatch)

	with pytest.raises(RemoteEndpointError, match = re.escape('"anwser" is not a capability of this Endpoint. Use list_capabilities()')):
		call(endpoint)

	assert requests == []


# The last response

def test_remote_endpoint_last_response_starts_empty(monkeypatch):
	""" Has no last response before the first call. """

	endpoint, _ = _endpoint(monkeypatch)

	assert endpoint.last_response is None


def test_remote_endpoint_last_response_keeps_complete_response(monkeypatch):
	""" Keeps the complete response, with the history, after an easy call. """

	response = {'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'Elena Ruiz.'}, 'history': [{'role': 'user'}]}
	endpoint, _ = _endpoint(monkeypatch, response)

	endpoint.run('answer', 'question')

	assert endpoint.last_response == response


def test_remote_endpoint_last_response_kept_on_error_finish(monkeypatch):
	""" Keeps the response of a call that finishes with an error, so its history can be inspected. """

	response = {'finish_reason': 'error', 'message': 'The tool failed.', 'history': [{'role': 'user'}]}
	endpoint, _ = _endpoint(monkeypatch, response)

	with pytest.raises(RemoteEndpointError):
		endpoint.run('answer', 'question')

	assert endpoint.last_response == response


def test_remote_endpoint_last_response_reset_without_response(monkeypatch):
	""" Leaves no last response when a call does not get a response. """

	endpoint, _ = _endpoint(monkeypatch, _stop(), urllib.error.URLError('refused'))
	endpoint.run('answer', 'question')

	with pytest.raises(RemoteEndpointError):
		endpoint.run('answer', 'question')

	assert endpoint.last_response is None


# Errors from the Endpoint

@pytest.mark.parametrize('body, detail', [
	(b'{"detail": "Crawl functionality is not yet implemented."}', 'Crawl functionality is not yet implemented.'),
	(b'{"detail": ""}', 'the Endpoint gave no details.'),
	(b'not json', 'the Endpoint gave no details.')
], ids = ['detail', 'empty detail', 'not json'])
def test_remote_endpoint_run_http_error(monkeypatch, body, detail):
	""" Raises with the detail that the Endpoint sends with an HTTP error. """

	endpoint, _ = _endpoint(monkeypatch, _http_error(body))

	with pytest.raises(RemoteEndpointError, match = re.escape('"answer" failed on the Endpoint (HTTP 500): ' + detail)):
		endpoint.run('answer', 'question')


def test_remote_endpoint_run_http_error_is_chained(monkeypatch):
	""" Keeps the original HTTP error as the cause. """

	error = _http_error(b'{"detail": "Run failed."}')
	endpoint, _ = _endpoint(monkeypatch, error)

	with pytest.raises(RemoteEndpointError) as raised:
		endpoint.run('answer', 'question')

	assert raised.value.__cause__ is error


def test_remote_endpoint_metadata_http_error(monkeypatch):
	""" Raises with the detail of an HTTP error when reading the metadata. """

	_mock_responses(monkeypatch, [_http_error(b'{"detail": "Invalid state."}')])

	with pytest.raises(RemoteEndpointError, match = re.escape('Reading the metadata failed on the Endpoint (HTTP 500): Invalid state.')):
		RemoteEndpoint('http://endpoint')


def test_remote_endpoint_not_answering_when_created(monkeypatch):
	""" Explains that no Endpoint is answering when it cannot be reached. """

	_mock_responses(monkeypatch, [urllib.error.URLError(ConnectionRefusedError(61, 'Connection refused'))])

	with pytest.raises(RemoteEndpointError, match = re.escape('No Endpoint is answering at http://endpoint. Start it with `mge serve')):
		RemoteEndpoint('http://endpoint')


def test_remote_endpoint_not_answering_in_a_call(monkeypatch):
	""" Explains that no Endpoint is answering when the connection is lost after it was created. """

	endpoint, _ = _endpoint(monkeypatch, ConnectionResetError(54, 'Connection reset by peer'))

	with pytest.raises(RemoteEndpointError, match = re.escape('No Endpoint is answering at http://endpoint.')):
		endpoint.run('answer', 'question')


# Dry runs

def test_remote_endpoint_dry_run(monkeypatch):
	""" Sends dry-run requests and returns the remote response. """

	result = {'status': 0, 'description': 'Valid request.'}
	endpoint, requests = _endpoint(monkeypatch, result)

	assert endpoint.dry_run('answer', {'question': 'question'}) == result
	assert requests[0].full_url == 'http://endpoint/dry_run'


def test_remote_endpoint_dry_run_does_not_check_arguments(monkeypatch):
	""" Sends invalid arguments in a dry run, since validating them is what the Endpoint does there. """

	endpoint, requests = _endpoint(monkeypatch, {'status': 1, 'description': 'Missing argument.'})

	endpoint.dry_run('answer', {})

	assert json.loads(requests[0].data) == {'name': 'answer', 'arguments': {}}
