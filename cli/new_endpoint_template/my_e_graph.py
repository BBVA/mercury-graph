from mercury.graph.evidence import Agentic, AgenticRunException, AlwaysReadyState

class MyCustomGraph(Agentic):

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		""" This is an example, you can inherit from: Agent, Agentic, AgenticGraph, EvidenceGraph, Formalizer, Source, or any
			class in mercury.graph.evidence that inherits from Agentic.

			To build your own library, just provide the source files and place appropriate imports so that the Endpoint can do:

			from my_library import MyCustomGraph

			You must preserve the (schema, endpoint, logger, extra_args) signature in the constructor.

			Your class is responsible to provide valid extra_args to the parent when you inherit any class other than Agentic.

		"""
		super().__init__(my_class = 'my_custom_graph', schema = schema, endpoint = endpoint, logger = logger)


	# Cannot implement an Agentic without overriding this @abstractmethod.
	def _run(self, request):

		raise AgenticRunException


	# Cannot implement an Agentic without overriding this @abstractmethod.
	def _meta(self):
		meta = {}
		meta['state'] = AlwaysReadyState.INITIAL.value

		return meta


	# Cannot implement an Agentic without overriding this @abstractmethod.
	def _dry_run(self, request):

		return {'status': 0, 'description': 'Valid request.'}
