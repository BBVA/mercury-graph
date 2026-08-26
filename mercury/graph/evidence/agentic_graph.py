from enum import Enum

from .agentic import Agentic, AgenticRunInvalidState, AlwaysReadyState
from mercury.graph.core import Graph


class GraphState(Enum):
	""" The `GraphState` is an enumeration that defines all possible states of an AgenticGraph. """

	ERR_GRAPH_INIT		= -1	# Something failed loading the graph.

	INITIAL				=  0	# The initial state of the graph.
	GRAPH_LOADED_OK		=  1	# The graph was loaded successfully.

	READY				=  100	# The graph is ready to be queried.


class AgenticGraph(Agentic):
	""" AgenticGraph is a class that exposed a `mercury.graph.Graph` in the Agentic tree.

	## Overview

	All the underlying technologies are supported, but typically the graph will be stored in RAM.

	The class also provides functionality to manage entire graphs as an Agentic `schema` providing persistence and concurrency.

	Ontologies, dictionaries and storages that in general will expect key/value stores are just a special case of graphs (without edges).
	Therefore, this is also the storage for all these things.

	Args:
		schema (str): a schema (a unique name) to use for the AgenticGraph's ID.
		extra_args (dict): the configuration for the AgenticGraph.
		endpoint (Agentic): an optional Endpoint. It becomes part of the AgenticGraph's ID and is available via `self.endpoint`. If not
			provided, the AgenticGraph becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'agentic_graph', schema = schema, endpoint = endpoint, logger = logger)

		self.conf = extra_args


	def _run(self, request):
		""" Runs the AgenticGraph with the given request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""
		raise AgenticRunInvalidState


	def _meta(self):
		""" Returns the metadata of the AgenticGraph.

			(See [`Agentic.meta()`][mercury.graph.evidence.Agentic.meta].)
		"""
		return {'state' : AlwaysReadyState.INITIAL.value}


	def _dry_run(self, request):
		""" Simulates running the AgenticGraph with the given request.

			(See [`Agentic.dry_run()`][mercury.graph.evidence.Agentic.dry_run].)
		"""
		return {'status': 1, 'description': 'Not ready.'}
