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
	""" AgenticGraph is the class that exposes a `mercury.graph.Graph` using the Agentic interface.

	## Overview

	A graph is a persisted storage of anything: the storage of nodes is a key/value store with any properties. On top of that, nodes
	can be connected by edges that also have properties. AgenticGraph objects are persisted. They can read from .csv files that
	contain ontologies, for initialization, but do not write to .csv files to keep project management simple. Once the graph is
	initialized, it stores itself as a pickle file. When initializing the object, if the pickle file exists, it will be loaded rather
	than initializing the graph from .csv files.

	## How AgenticGraphs are used to build EvidenceGraphs

	There a three components: the Ontology (which is just a graph with a structure the Formalizer understands) keeps the concepts for
	both the entities and the relationships and also the indices of each node or relation in an EvidenceGraph. The Formalizer takes
	the concepts from the Ontology (E.g., person, product, country, etc.) and the relationships (E.g., is_owned_by, is_located_in, etc.)
	and finds instances of those concepts in natural language text. The EvidenceGraph creates an aggregated graph of all that information
	handling contradictions, reinforcements and confidence.

	## What the AgenticGraph exposes via the Agentic interface

	All the internals of a graph are basically understood by the Formalizer and the EvidenceGraph. The AgenticGraph is an understandable
	storage for concepts, entity indices and relationships and, via the Agentic interface that is what is accessible: A mechanism
	similar to that of a source to retrieve, via unique indices, concepts, entities and relationships.

	## Known Limitations

	There is no "graph language" exposed via the Agentic interface that allows for arbitrary graph oriented queries. That may be added
	in the future to leverage on the functionality the underlying graph class already has.

	Args:
		schema (str): a schema (a unique name) to use for the AgenticGraph's ID.
		extra_args (dict): the configuration for the AgenticGraph. See the configuration for the examples in ontologies.jsonc for
			reference on how to configure the AgenticGraph's persistence.
		endpoint (Agentic): an optional Endpoint. It becomes part of the AgenticGraph's ID and is available via `self.endpoint`. If not
			provided, the AgenticGraph becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'agentic_graph', schema = schema, endpoint = endpoint, logger = logger)

		self.states = GraphState

		self.conf = extra_args
		self.name = schema

		self._graph	= None

		self._meta_ = self._meta()	# Just to make .meta reflect the initial state.


	def _run(self, request):
		""" Runs the AgenticGraph with the given request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""
		raise AgenticRunInvalidState


	def _meta(self):
		""" Returns the metadata of the AgenticGraph.

			(See [`Agentic.meta()`][mercury.graph.evidence.Agentic.meta].)
		"""
		meta = {}
		meta['state'] = GraphState.INITIAL.value
		meta['conf'] = self.conf
		meta['capabilities'] = self._capabilities()

		return meta


	def _dry_run(self, request):
		""" Simulates running the AgenticGraph with the given request.

			(See [`Agentic.dry_run()`][mercury.graph.evidence.Agentic.dry_run].)
		"""
		return {'status': 1, 'description': 'Not ready.'}
