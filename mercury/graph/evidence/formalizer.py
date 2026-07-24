from .agentic import Agentic, AgenticRunInvalidState, AlwaysReadyState


class Formalizer(Agentic):
	""" The Formalizer is the class that takes in natural language and produces structured data in the form of subgraphs.

	It uses:

	1. Ontologies for categories of entities and relationships.
	2. The (SIE) Structured Information Extracting Tools (E.g. GLiNER2).
	3. It produces subgraphs that can be:

		- Merged into the EvidenceGraph.
		- Used by the Agent to answer grounded queries.

	"""

	def __init__(self, schema = None, endpoint = None, logger = None, extra_args = None):
		super().__init__(my_class = 'formalizer', schema = schema, endpoint = endpoint, logger = logger)

		if extra_args is not None:
			self.conf = extra_args
		else:
			self.conf = {}


	def _run(self, request):
		raise AgenticRunInvalidState


	def _meta(self):
		return {'state' : AlwaysReadyState.INITIAL.value}


	def _dry_run(self, request):
		return {'status': 1, 'description': 'Not ready.'}
