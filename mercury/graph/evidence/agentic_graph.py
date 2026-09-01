import os, pickle

from enum import Enum

import pandas as pd

from .agentic import Agentic, AgenticRunInvalidRequest
from mercury.graph.core import Graph


class GraphState(Enum):
	""" The `GraphState` is an enumeration that defines all possible states of an AgenticGraph. """

	ERR_GRAPH_INIT		= -1	# Something failed loading the graph.

	INITIAL				=  0	# The initial state of the graph.
	GRAPH_LOADED_OK		=  1	# The graph was loaded successfully.

	READY				=  100	# The graph is ready to be queried.


class AgenticGraph(Agentic):
	""" AgenticGraph is the class that exposes a `mercury.graph.Graph` using the Agentic interface.

	## AgenticGraphs are typically persisted

	A graph is a persisted storage of anything: the storage of nodes is a key/value store with any properties. On top of that, nodes
	can be connected by edges that also have properties. AgenticGraph objects are typically persisted (that is part of their configuration
	to store such things as hierarchical ontologies for both entities and relationships). They can read from .csv files that
	contain ontologies, for initialization, but do not write to .csv files to keep project management simple. Once the graph is
	initialized, it stores itself as a pickle file. When initializing the object, if the pickle file exists, it will be loaded rather
	than initializing the graph from .csv files.

	## IDs and hierarchical structure

	The ontology is not only the place where concepts and relationships are defined to be used by the formalizer, but also the
	place where the IDs of every node and edge in the EvidenceGraph live. Despite the number of entities being potentially very large and
	AgenticGraphs typically living in RAM, the importance of creating concepts and maintaining the hierarchical structure dynamically from
	text by Agentic decisions makes this "all in one place" design recommendable. Also, the mechanism used to structure text entities using
	[`SourceNode`][mercury.graph.evidence.source_parts.SourceNode] is exactly the mechanism used in the hierarchy of the IDs.

	## How AgenticGraphs are used to build EvidenceGraphs

	There a three components:

	* The Ontologies are just graphs with IDs and definitions for concepts. Typically entities and
	relationships live in different graphs (relationships may not be used, all that is configurable).
	* The Formalizer takes concepts defined in the Ontology (E.g., person, product, country, etc.) also possibly relationships
	(E.g., is_owned_by, is_located_in, etc.) and finds instances of those concepts in natural language text.
	* The EvidenceGraph creates an aggregated graph of all that information handling contradictions, reinforcements and confidence.

	## What the AgenticGraph exposes via the Agentic interface

	All the internals of a graph are basically understood by the Formalizer and the EvidenceGraph. The AgenticGraph is an understandable
	storage for concepts, entity indices and relationships and, via the Agentic interface that is what is accessible: A mechanism
	similar to that of a source to retrieve, via unique indices, concepts, entities and relationships.

	## Known Limitations

	There is no "graph language" exposed via the Agentic interface that allows for arbitrary graph oriented queries. Note that Agentic
	objects have a mechanism to access the objects directly and will typically bypass the Agentic interface for intense computations such
	as crawling entire corpora. In the future, Agents, besides discovering the hierarchy tree may also have to modify it by creating or
	updating concepts and relationships.

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

		call = self.call.get(request['name'], None)

		if call is None:
			self.log_error('AgenticGraph does not have a function named "%s".' % request['function'])
			raise AgenticRunInvalidRequest

		index = request['arguments'].get('index', None)

		if index is None:
			self.log_error('AgenticGraph function "%s" requires an "index" argument.' % request['function'])
			raise AgenticRunInvalidRequest

		ret = {'finish_reason': 'stop', 'message': call(index)}

		return ret


	def _meta(self):
		""" Returns the metadata of the AgenticGraph.

			(See [`Agentic.meta()`][mercury.graph.evidence.Agentic.meta].)
		"""

		meta = {}
		meta['state'] = GraphState.INITIAL.value

		meta['description'] = self.conf.get('description', '')
		if type(meta['description']) is list:
			meta['description'] = '\n'.join(meta['description'])

		meta['capabilities'] = self._capabilities()

		return meta


	def _dry_run(self, request):
		""" Simulates running the AgenticGraph with the given request.

		(See [`Agentic.dry_run()`][mercury.graph.evidence.Agentic.dry_run].)

		## NOTE:

		The Endpoint takes care of validating the request according to the capabilities exposed by the AgenticGraph. It is not necessary to
		validate again here and the Endpoint does not forward the dry_run() request to the AgenticGraph. This method is provided as a
		requirement of the Agentic interface, but it is only used when you use AgenticGraphs directly outside of an Endpoint.
		"""

		return {'status': 0, 'description': 'Valid request.'}


	def pilot(self, intent, just_once = False):
		""" Pilots the AgenticGraph to a new state based on the given intent.

		(See [`Agentic.pilot()`][mercury.graph.evidence.Agentic.pilot].)
		"""

		def new_graph():
			""" Creates a new graph when there is no persisted graph to load, but possibly initial_nodes and/or initial_edges. """

			keys = self.conf.get('file_format', None)
			if keys is None:
				keys = {'src': 'src', 'dst': 'dst', 'id': 'id', 'weight': 'weight', 'directed': True, 'sep': '\t'}

			nodes = None
			fn_nodes = self.conf.get('initial_nodes', None)
			if fn_nodes is not None:
				if fn_nodes['type'] == 'csv':
					sep = ',' if keys is None or 'sep' not in keys else keys['sep']
					nodes = pd.read_csv(fn_nodes['path'], sep = sep)
				elif fn_nodes['type'] == 'pickle':
					nodes = pd.read_pickle(fn_nodes['path'])

			fn_edges = self.conf.get('initial_edges', None)
			if fn_edges is not None:
				if fn_edges['type'] == 'csv':
					sep = ',' if keys is None or 'sep' not in keys else keys['sep']
					edges = pd.read_csv(fn_edges['path'], sep = sep)
				elif fn_edges['type'] == 'pickle':
					edges = pd.read_pickle(fn_edges['path'])
			else:
				edges = pd.DataFrame({keys['src']: pd.Series(dtype='str'), keys['dst']: pd.Series(dtype='str')})

			return Graph(data = edges, keys = keys, nodes = nodes)


		if self.meta['state'] < 0:
			self.log_error('AgenticGraph is in error state %d' % self._meta_['state'])

			return

		while self._meta_['state'] < intent:
			if self._meta_['state'] == self.states.INITIAL.value:
				try:
					self._fname = self.conf.get('persistence', None)
					if self._fname is None:
						self._graph = new_graph()
					else:
						self._fname = self._fname['path']
						parent_dir	= os.path.dirname(self._fname)

						if parent_dir:
							os.makedirs(parent_dir, exist_ok = True)

						if os.path.isfile(self._fname):
							with open(self._fname, 'rb') as f:
								ntx = pickle.load(f)			# A NetworkX graph object saved by this class.
							self._graph = Graph(data = ntx)
						else:
							self._graph = new_graph()

				except:
					self.log_error('Graph could not be created and initialized for AgenticGraph "%s".' % self.name)
					self._meta_['state'] = self.states.ERR_GRAPH_INIT.value
					break

				self._meta_['state'] = self.states.GRAPH_LOADED_OK.value

				if just_once:
					break

			if self._meta_['state'] == self.states.GRAPH_LOADED_OK.value:
				self._build_indices()
				self._meta_['state'] = self.states.READY.value

				break


	def get_children_idx(self, index = None):
		""" Returns the children indices following the SourceNode interface.

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source_parts.SourceNode.get_children_idx].)
		"""

		return None
		# TODO: Implement this method.


	def child(self, index):
		""" Returns the corresponding SourceNode object following the SourceNode interface and serializes it to a dictionary.

		(See [`SourceNode.child()`][mercury.graph.evidence.source_parts.SourceNode.child].)
		"""

		return None
		# TODO: Implement this method.


	def close(self, endpoint_locked):
		""" Closes the AgenticGraph, persists it to disk and releases any resources it holds.

		(See [`Agentic.close()`][mercury.graph.evidence.Agentic.close].)
		"""

		if endpoint_locked and self._graph is not None and self._fname is not None:
			ntx = self._graph.networkx
			with open(self._fname, 'wb') as f:
				pickle.dump(ntx, f)

		self._graph = None


	def _build_indices(self):
		""" Builds the indices for the AgenticGraph for the first time after it is loaded.

		This iterates though the id attributes of the nodes and edges in self._graph. and parses
		the ID breaking then by their | character. The result is stored in a tree of dictionaries
		where the root is self._children.
		"""

		self._children = {}

		for id, _ in self._graph.networkx.nodes.data('id'):
			d  = self._children
			ii = id.split('|')

			last = len(ii) - 1

			for i, ix in enumerate(ii):
				if i == last:
					d[ix] = None
				else:
					if ix not in d or d[ix] is None:
						d[ix] = {}

					d = d[ix]

		for _, _, id in self._graph.networkx.edges.data('id'):
			d  = self._children
			ii = id.split('|')

			last = len(ii) - 1

			for i, ix in enumerate(ii):
				if i == last:
					d[ix] = None
				else:
					if ix not in d or d[ix] is None:
						d[ix] = {}

					d = d[ix]


	def _capabilities(self):
		""" Returns the capabilities of the AgenticGraph.

		Returns:
			(list): A list of capabilities, each represented as a dictionary with the following keys:

				- 'type': The type of capability (e.g., 'function').
				- 'function': A dictionary containing details about the function

				The value of 'function' is:

				* 'name': The name of the function.
				* 'description': A brief description of what the function does.
				* 'parameters': A dictionary with 'type', 'properties', and 'required'
				* 'returns': A dictionary with 'type' and 'items'
		"""

		name_children_idx = 'children_by_idx_%s' % self.name
		name_node_by_idx  = 'node_by_idx_%s' % self.name

		self.call = {name_children_idx: self.get_children_idx, name_node_by_idx: self.child}

		return [
			{
				'type': 'function',
				'function': {
					'name': name_children_idx,
					'description': 'Get indices of the children of an index.',
					'parameters': {
						'type': 'object',
						'properties': {
							'index': {
								'type': 'string',
								'description': 'Index whose children indices are required.'
							}
						},
						'required': ['index']
					},
					'returns': {
						'type': 'array',
						'items': {
							'type': 'string'
						}
					}
				}
			},
			{
				'type': 'function',
				'function': {
					'name': name_node_by_idx,
					'description': 'Get the properties of a node by its index.',
					'parameters': {
						'type': 'object',
						'properties': {
							'index': {
								'type': 'string',
								'description': 'Index of the node.'
							}
						},
						'required': ['index']
					},
					'returns': {
						'type': 'string'
					}
				}
			}
		]
