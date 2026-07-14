from .agentic import Agentic


class EvidenceGraph(Agentic):
	""" The EvidenceGraph is the class that holds the knowledge about one or many sources in the form of a graph.

	## Overview

	This is the core of the architecture.

	It contains the aggregation of all knowledge with complete traceability of every entity and relationship in the graph.

	The graph structure enables capabilities that are difficult in standard RAG systems:

	- Finding relevant answers to questions that are not similar to any single chunk.
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

	"""

	def __init__(self, schema = None, parent = None, logger = None, extra_args = None):
		super().__init__(my_class = 'evidence_graph', schema = schema, parent = parent, logger = logger)

		if extra_args is not None:
			self.conf = extra_args
		else:
			self.conf = {}


	def _run(self, request):
		return {'status': 'ok'}


	def _meta(self):
		return {'status': 'ok'}


	def _dry_run(self, request):
		return {'status': 'ok'}
