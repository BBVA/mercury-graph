
from .agentic import Agentic


class Crawl():
	""" A Crawl object recurses a tree in a domain up to a limited boundary and propagates its information to multiple targets.
	This is used typically by an EvidenceGraph, both for growing and exploring a Source (both the text and the vector representation)
	or an AgenticGraph.

	Typical usage includes:

	* Crawl the text of a source and formalize it into structured knowledge.
	* Crawl an similar vector in the embedding space of a Source.
	* Crawl an AgenticGraph by ontology.

	"""

	def __init__(self, domain, boundary, targets):
		pass

	@property
	def done(self):
		pass

	@property
	def nodes_done(self):
		pass

	@property
	def nodes_seen(self):
		pass

	def run(self, num_steps = 0):
		pass
