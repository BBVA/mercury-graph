from mercury.graph.evidence import Agentic


class AgenticGraph(Agentic):
	""" AgenticGraph is a class that exposed a `mercury.graph.Graph` in the Agentic tree.

	## Overview

	All the underlying technologies are supported, but typically the graph will be stored in RAM.

	The class also provides functionality to manage entire graphs as an Agentic `schema` providing persistence and concurrency.

	Ontologies, dictionaries and storages that in general will expect key/value stores are just a special case of graphs (without edges).
	Therefore, this is also the storage for all these things.

	"""

	def __init__(self, schema = None, parent = None, logger = None):
		super().__init__(my_class = 'agentic_graph', schema = schema, parent = parent, logger = logger)
