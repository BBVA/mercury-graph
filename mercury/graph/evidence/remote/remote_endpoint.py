import json
import urllib.request


class RemoteEndpointError(Exception):
	""" Raised when a request to a remote Endpoint cannot be made or the Endpoint answers with an error. """


class RemoteEndpoint:
	""" This is a utility class for interacting with an Endpoint that is served using the `mge` CLI.

	It only provides a subset of the functionality and is intended for quick testing.

	Args:
		base_url (str): The URL of the endpoint as shown by the CLI (E.g., Uvicorn running on http://0.0.0.0:8765 (Press CTRL+C to quit))

	Attributes:
		capabilities (list): The capabilities of the remote endpoint, in the OpenAI tools format, as given by its metadata.
		last_response (dict): The complete response of the last call to `run()`, including the `history` of an agent's tool calls when
			the Endpoint provides it. None before the first call and when the last call did not get a response.
	"""

	def __init__(self, base_url):
		self.base_url = base_url

		self.capabilities  = self.get_capabilities()
		self._functions	   = self._parse_capabilities()
		self.last_response = None


	def get_capabilities(self):
		""" Fetch the capabilities of the remote endpoint.

		Returns:
			(list): A list of capabilities exposed by the remote endpoint.
		"""

		with urllib.request.urlopen('%s/meta' % self.base_url) as response:
			meta = json.load(response)

		capabilities = meta.get('capabilities')

		if capabilities is None:
			raise RuntimeError('The Endpoint metadata does not expose capabilities.')

		return capabilities


	def list_capabilities(self):
		""" List the names of the capabilities exposed by the remote endpoint.

		Each name is unique in the Endpoint and is the first argument of `run()`.

		Returns:
			(list): The names of the capabilities, in the order given by the Endpoint.
		"""

		return list(self._functions.keys())


	def describe(self, name):
		""" Describe a capability of the remote endpoint: what it does and which arguments it takes.

		Args:
			name (str): The name of the capability, as returned by `list_capabilities()`.

		Returns:
			(dict): A dictionary with the keys 'name', 'description' and 'arguments'. 'arguments' maps each argument name to a
				dictionary with its 'type', 'description' and whether it is 'required'.
		"""

		fun = self._functions[name]

		arguments = {nam: dict(arg) for nam, arg in fun['arguments'].items()}

		return {'name': name, 'description': fun['description'], 'arguments': arguments}


	def _parse_capabilities(self):
		""" Parse the capabilities of the remote endpoint into a dictionary of functions, used by `run()` and `describe()`.

		Returns:
			(dict): A dictionary, keyed by capability name, with the description and the arguments of each capability.
		"""

		functions = {}

		for cap in self.capabilities:
			assert cap['type'] == 'function'

			key = cap['function']['name']
			dsc = cap['function']['description']

			assert cap['function']['parameters']['type'] == 'object'

			req = cap['function']['parameters'].get('required', [])

			args = {}

			for nam, val in cap['function']['parameters']['properties'].items():
				args[nam] = {'type': val['type'], 'description': val.get('description', ''), 'required': nam in req}

			functions[key] = {'description': dsc, 'arguments': args}

		return functions


	def run(self, fun_name, args, easy = True):
		""" Run a function on the remote endpoint.

		The complete response is always stored in `last_response`, so the `history` of an agent's tool calls can be inspected after
		an easy call.

		Args:
			fun_name (str): The name of the function to run.
			args (dict or str): The arguments to pass to the function. When `easy` is True, it can also be a string, which becomes the
				value of the only required argument (or of the only argument, if none is required) when that argument is a string.
			easy (bool, optional): If True, simplifies argument passing and returns the result itself: the `message` of the response,
				or its `content` for an agent. A response that finishes with an error raises a RemoteEndpointError instead. If False,
				returns the complete response. Defaults to True.

		Returns:
			(Any): The result of the function when `easy` is True, the complete response otherwise.
		"""

		fun = self._functions[fun_name]

		if easy and type(args) is str:
			args = self._text_as_arguments(fun_name, fun, args)

		self.last_response = None

		data = json.dumps({'name': fun_name, 'arguments': args}).encode('utf-8')

		req = urllib.request.Request('%s/run' % self.base_url, data = data, headers = {'content-type': 'application/json'})

		with urllib.request.urlopen(req) as response:
			result = json.load(response)

		self.last_response = result

		if not easy or type(result) is not dict or 'finish_reason' not in result or 'message' not in result:
			return result

		message = result['message']

		if type(message) is dict and 'content' in message:
			message = message['content']

		if str(result['finish_reason']).lower().startswith('error'):
			raise RemoteEndpointError('"%s" finished with an error: %s' % (fun_name, message))

		return message


	def _text_as_arguments(self, fun_name, fun, text):
		""" Builds the arguments of a function from a single text, as `run()` does when `easy` is True.

		Args:
			fun_name (str): The name of the function.
			fun (dict): The function, as parsed by `_parse_capabilities()`.
			text (str): The text.

		Returns:
			(dict): The arguments, with the text as the value of the only required argument (or of the only argument, if none is
				required) when that argument is a string.
		"""

		arguments = fun['arguments']

		names = [nam for nam, arg in arguments.items() if arg['required']]
		kind  = 'required'
		if len(names) == 0:
			names = list(arguments.keys())
			kind  = 'optional'

		if len(names) == 1 and arguments[names[0]]['type'] == 'string':
			return {names[0]: text}

		if len(names) == 0:
			raise RemoteEndpointError('"%s" takes no arguments. Pass an empty dictionary: {}.' % fun_name)

		if len(names) > 1:
			reason = 'takes %d %s arguments but only one text was given' % (len(names), kind)
		else:
			reason = 'takes its argument "%s" as %s, not as text' % (names[0], arguments[names[0]]['type'])

		raise RemoteEndpointError('"%s" %s. Pass a dictionary with its arguments: %s.' % (fun_name, reason, ', '.join(arguments.keys())))


	def dry_run(self, fun_name, args):
		""" Perform a dry run of a function on the remote endpoint.

		Args:
			fun_name (str): The name of the function to dry run.
			args (dict): The arguments to pass to the function.

		Returns:
			(dict): The result of the dry run.
		"""

		fun = self._functions[fun_name]

		data = json.dumps({'name': fun_name, 'arguments': args}).encode('utf-8')

		req = urllib.request.Request('%s/dry_run' % self.base_url, data = data, headers = {'content-type': 'application/json'})

		with urllib.request.urlopen(req) as response:
			result = json.load(response)

		return result
