import json
import urllib.request


class RemoteEndpoint:
	""" This is a utility class for interacting with an Endpoint that is served using the `mge` CLI.

	It only provides a subset of the functionality and is intended for quick testing.

	Args:
		base_url (str): The URL of the endpoint as shown by the CLI (E.g., Uvicorn running on http://0.0.0.0:8765 (Press CTRL+C to quit))

	"""

	def __init__(self, base_url):
		self.base_url = base_url

		self.capabilities = self.get_capabilities()
		self.functions	  = self.get_functions()


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


	def get_functions(self):
		""" Fetch the functions exposed by the remote endpoint.

		Returns:
			(dict): A dictionary of functions with their descriptions and arguments.
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
				args[nam] = {'typ': val['type'], 'dsc': val.get('description', ''), 'req': nam in req}

			functions[key] = {'dsc': dsc, 'args': args}

		return functions


	def run(self, fun_name, args, easy = True):
		""" Run a function on the remote endpoint.

		Args:
			fun_name (str): The name of the function to run.
			args (dict): The arguments to pass to the function.
			easy (bool, optional): If True, attempts to simplify argument passing and result handling. Defaults to True.

		Returns:
			(Any): The result of the function execution, potentially simplified if `easy` is True.
		"""

		fun = self.functions[fun_name]

		if easy:

			if type(args) is str and len(fun['args']) == 1:
				key, val = next(iter(fun['args'].items()))
				if val['typ'] == 'string':
					args = {key: args}

		data = json.dumps({'name': fun_name, 'arguments': args}).encode('utf-8')

		req = urllib.request.Request('%s/run' % self.base_url, data = data, headers = {'content-type': 'application/json'})

		with urllib.request.urlopen(req) as response:
			result = json.load(response)

		if easy:

			if type(result) is dict and 'finish_reason' in result and 'message' in result and not 'history' in result:
				if result['finish_reason'] == 'stop':
					message = result['message']

					if type(message) is dict and 'content' in message:
						message = message['content']

					return message

		return result


	def dry_run(self, fun_name, args):
		""" Perform a dry run of a function on the remote endpoint.

		Args:
			fun_name (str): The name of the function to dry run.
			args (dict): The arguments to pass to the function.

		Returns:
			(dict): The result of the dry run.
		"""

		fun = self.functions[fun_name]

		data = json.dumps({'name': fun_name, 'arguments': args}).encode('utf-8')

		req = urllib.request.Request('%s/dry_run' % self.base_url, data = data, headers = {'content-type': 'application/json'})

		with urllib.request.urlopen(req) as response:
			result = json.load(response)

		return result
