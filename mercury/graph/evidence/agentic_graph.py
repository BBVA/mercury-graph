from .agentic import Agentic, AgenticRunInvalidState, AlwaysReadyState


class AgenticGraph(Agentic):
	""" AgenticGraph is a class that exposed a `mercury.graph.Graph` in the Agentic tree.

	## Overview

	All the underlying technologies are supported, but typically the graph will be stored in RAM.

	The class also provides functionality to manage entire graphs as an Agentic `schema` providing persistence and concurrency.

	Ontologies, dictionaries and storages that in general will expect key/value stores are just a special case of graphs (without edges).
	Therefore, this is also the storage for all these things.

	"""

	def __init__(self, schema = None, endpoint = None, logger = None, extra_args = None):
		super().__init__(my_class = 'agentic_graph', schema = schema, endpoint = endpoint, logger = logger)

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
