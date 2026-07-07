from .agentic import Agentic


class Formalizer(Agentic):
	""" The Formalizer is the class that takes in natural language and produces structured data in the form of subgraphs.

	It uses:

	1. Ontologies for categories of entities and relationships.
	2. The (SIE) Structured Information Extracting Tools (E.g. GLiNER2).
	3. It produces subgraphs that can be:

		- Merged into the EvidenceGraph.
		- Used by the Agent to answer grounded queries.

	"""

	def __init__(self, schema = None, parent = None, logger = None):
		super().__init__(my_class = 'formalizer', schema = schema, parent = parent, logger = logger)


	def _run(self, request):
		return {'status': 'ok'}


	def _meta(self):
		return {'status': 'ok'}


	def _dry_run(self, request):
		return {'status': 'ok'}
