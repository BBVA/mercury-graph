from .agentic import Agentic, AgenticRunInvalidState, AlwaysReadyState


class EvidenceGraph(Agentic):
	""" The EvidenceGraph is the class that holds the knowledge about one or many sources in the form of a graph.

	## Overview

	This is the core of the architecture.

	It contains the aggregation of all knowledge with complete traceability of every entity and relationship in the graph.

	The graph structure enables capabilities that are difficult in standard RAG systems:

	- Finding relevant answers to questions that are not similar to any single chunk of text.
	- Connecting entities and relations.
	- Evidence weighting, making sense of contradictions and reinforcements.
	- It does not replace RAG, it can be used in combination.

	Each text fragment (one or several sentences) is converted into a small graph:

	- Entities become nodes.
	- Extracted relations become edges.
	- The original text becomes traceable evidence attached to those relations.

	As more text is processed:

	- Equivalent entities are merged.
	- Relations accumulate evidence.
	- Confidence evolves.
	- Contradictions can be represented explicitly.

	The graph becomes a continuously evolving structured memory.

	An Agent interacts with this graph as an external reasoning tool:

	- Querying entities and relations.
	- Retrieving evidence.
	- Disambiguating ambiguous references.
	- Grounding responses in traceable sources.

	Args:
		schema (str): a schema (a unique name) to use for the EvidenceGraph's ID.
		extra_args (dict): the configuration for the EvidenceGraph.
		endpoint (Agentic): an optional Endpoint. It becomes part of the EvidenceGraph's ID and is available via `self.endpoint`. If not
			provided, the EvidenceGraph becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'evidence_graph', schema = schema, endpoint = endpoint, logger = logger)

		self.conf = extra_args


	def _run(self, request):
		""" Runs the EvidenceGraph with the given request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""
		raise AgenticRunInvalidState


	def _meta(self):
		""" Returns the metadata of the EvidenceGraph.

			(See [`Agentic.meta()`][mercury.graph.evidence.Agentic.meta].)
		"""
		return {'state' : AlwaysReadyState.INITIAL.value}


	def _dry_run(self, request):
		""" Simulates running the EvidenceGraph with the given request.

			(See [`Agentic.dry_run()`][mercury.graph.evidence.Agentic.dry_run].)
		"""
		return {'status': 1, 'description': 'Not ready.'}
