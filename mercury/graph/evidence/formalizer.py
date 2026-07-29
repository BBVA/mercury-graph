from .agentic import Agentic, AgenticRunInvalidState, AlwaysReadyState


class Formalizer(Agentic):
	""" The Formalizer is the class that takes in natural language and produces structured data in the form of subgraphs.

	It uses:

	1. Ontologies for categories of entities and relationships.
	2. The (SIE) Structured Information Extracting Tools (E.g. GLiNER2).
	3. It produces subgraphs that can be:

		- Merged into the EvidenceGraph.
		- Used by the Agent to answer grounded queries.

	Args:
		schema (str): a schema (a unique name) to use for the Formalizer's ID.
		extra_args (dict): the configuration for the Formalizer.
		endpoint (Agentic): an optional Endpoint. It becomes part of the Formalizer's ID and is available via `self.endpoint`. If not
			provided, the Formalizer becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'formalizer', schema = schema, endpoint = endpoint, logger = logger)

		self.conf = extra_args


	def _run(self, request):
		""" Runs the Formalizer with the given request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""
		raise AgenticRunInvalidState


	def _meta(self):
		""" Returns the metadata of the Formalizer.

			(See [`Agentic.meta()`][mercury.graph.evidence.Agentic.meta].)
		"""
		return {'state' : AlwaysReadyState.INITIAL.value}


	def _dry_run(self, request):
		""" Simulates running the Formalizer with the given request.

			(See [`Agentic.dry_run()`][mercury.graph.evidence.Agentic.dry_run].)
		"""
		return {'status': 1, 'description': 'Not ready.'}
