import copy, os, pickle

from enum import Enum

import pandas as pd
import networkx as nx

from .agentic import Agentic, AgenticRunInvalidRequest
from mercury.graph.core import Graph


MAX_RESULTS = 50		# Default maximum number of entries in the answer of a capability (configurable as "max_results").
TRUNCATED	= {'truncated': True, 'hint': 'There are more results. Ask for something more specific (a longer id or text, or a smaller depth).'}

_MISSING	= object()	# Returned by AgenticGraph._subtree() for an id that is not in the navigation tree.


def parent_of(index):
	""" Returns the parent of a hierarchical id (the id without its last `|` level) or None if it has a single level. """

	return index.rsplit('|', 1)[0] if '|' in index else None


def descends_from(concept, ancestor):
	""" Returns True if concept is ancestor or one of its descendants in the `|` hierarchy (person_group does not descend from person). """

	return concept == ancestor or concept.startswith(ancestor + '|')


def _positive_int(value, default):
	""" Returns value as an integer if it is (or is text for) a number greater than zero and default otherwise. """

	try:
		return int(value) if int(value) > 0 else default

	except (TypeError, ValueError):
		return default


def _as_bool(value):
	""" Returns False for False or a text such as "false", "no" or "0" and True for anything else. """

	return str(value).strip().lower() not in ('false', 'no', '0')


def _declares(attr, end):
	""" Returns True if the attributes of a node declare end ('src' or 'dst') as a non-empty text. """

	return isinstance(attr.get(end, None), str) and attr[end] != ''


def _role(attr, concept, inherited):
	""" Returns the role ('src', 'dst' or 'both') of a concept in a relationship given its attributes, or None if it takes no part.
	With inherited, a concept also takes part where one of its ancestors does.
	"""

	roles = [end for end in ('src', 'dst') if _declares(attr, end) and (descends_from(concept, attr[end]) if inherited else concept == attr[end])]

	if len(roles) == 0:
		return None

	return roles[0] if len(roles) == 1 else 'both'


def _parameters(required, **properties):
	""" Returns the JSON schema of the parameters of a capability. """

	return {'type': 'object', 'properties': properties, 'required': required}


ID		= {'type': 'string', 'description': 'An id, written exactly as in the ontology (e.g., person|student). An empty string is the root.'}
LIST	= {'type': 'array', 'items': {'type': 'object'}}

CAPABILITIES = {
	'children_by_idx': {
		'description': 'Get the children of an id with their definitions, down to depth levels.',
		'parameters': _parameters(['index'], index = ID, depth = {'type': 'integer', 'description': 'Number of levels to go down. Defaults to 1.'}),
		'returns': LIST
	},
	'node_by_idx': {
		'description': 'Get the properties of a node by its id and its ancestors with their definitions.',
		'parameters': _parameters(['index'], index = ID),
		'returns': {'type': 'object'}
	},
	'search': {
		'description': 'Find the nodes whose id or definition contains a text, ignoring case.',
		'parameters': _parameters(['text'], text = {'type': 'string', 'description': 'The text to find.'},
								  limit = {'type': 'integer', 'description': 'Maximum number of results. Defaults to 20.'}),
		'returns': LIST
	},
	'edges': {
		'description': 'Get the edges going out of or coming into a node, optionally only those of a relation and its descendants.',
		'parameters': _parameters(['index'], index = ID,
								  relation = {'type': 'string', 'description': 'Only return edges of this relation or of relations under it.'}),
		'returns': LIST
	},
	'relations_for': {
		'description': 'Get the relationships a concept can take part in, as src, dst or both.',
		'parameters': _parameters(['concept'], concept = {'type': 'string', 'description': 'The id of a concept (e.g., person|student).'},
								  inherited = {'type': 'boolean', 'description': 'Include the relationships of its ancestors. Defaults to true.'}),
		'returns': LIST
	}
}


class GraphState(Enum):
	""" The `GraphState` is an enumeration that defines all possible states of an AgenticGraph. """

	ERR_BUILDING		= -2	# Something failed during the building of the graph.
	ERR_GRAPH_INIT		= -1	# Something failed loading the graph.

	INITIAL				=  0	# The initial state of the graph.
	GRAPH_LOADED_OK		=  1	# The graph was loaded successfully.

	READY				=  100	# The graph is ready to be queried.


class MultiGraph(Graph):
	""" MultiGraph is a subclass of Graph, implemented only for AgenticGraph.

	It demonstrates how to extend the original Graph class to support MultiDiGraph structures, but only supports NetworkX MultiDiGraph
	instead of all the technologies supported by the original Graph class. Its interactions with graph-specific functions and attributes
	in the original class are not guaranteed to work correctly.
	"""

	def __init__(self, data = None, keys = None, nodes = None):
		super().__init__(data = data, keys = keys, nodes = nodes)


	def _from_pandas(self, edges, nodes, keys):
		""" This internal method is overridden to construct a NetworkX MultiDiGraph (directed, not weighted) instead of the DiGraph() or
		Graph() of the original Graph class.
		"""

		src = keys.get('src', 'src')
		dst = keys.get('dst', 'dst')
		id  = keys.get('id', 'id')

		directed = keys.get('directed', True)

		if directed:
			g = nx.MultiDiGraph()
		else:
			raise NotImplementedError('Only directed graphs are currently supported.')

		for _, row in edges.iterrows():
			attr = row.drop([src, dst, id]).to_dict()
			g.add_edge(row[src], row[dst], key = row[id], **attr)

		if nodes is not None:
			for _, row in nodes.iterrows():
				attr = row.drop([id]).to_dict()
				g.add_node(row[id], **attr)

		self._from_networkx(g)


	def _calculate_edges_colnames(self):
		""" This internal method is overridden to add the key column for MultiDiGraph edges. """

		l = ['src', 'dst', 'key']
		k = self._as_networkx.edges.keys()
		if len(k) > 0:
			l.extend(list(self._as_networkx.edges[list(self._as_networkx.edges.keys())[0]].keys()))

		return l


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

		if schema is None:			# This allows finding out the class name (to link tools) without actually instantiating a full object.
			return

		self.states = GraphState

		self.conf = extra_args
		self.name = schema

		self._graph	= None

		self._meta_ = self._meta()	# Just to make .meta reflect the initial state.


	def _run(self, request):
		""" Runs the AgenticGraph with the given request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""

		name = request['name']
		call = self.call.get(name, None)

		if call is None:
			self.log_error('AgenticGraph does not have a function named "%s".' % name)
			raise AgenticRunInvalidRequest

		args = request['arguments']
		missing = self._missing_arguments(name, args)

		if len(missing) > 0:
			self.log_error('AgenticGraph function "%s" requires the argument "%s".' % (name, missing[0]))
			raise AgenticRunInvalidRequest

		return {'finish_reason': 'stop', 'message': call(args)}


	def _missing_arguments(self, name, arguments):
		""" Returns the required arguments of the capability called name (as declared in its definition) that are missing or None. """

		for capability in self._meta_['capabilities']:
			if capability['function']['name'] == name:
				required = capability['function']['parameters'].get('required', [])

				return [argument for argument in required if arguments.get(argument, None) is None]

		return []


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
				keys = {'src': 'src', 'dst': 'dst', 'id': 'id', 'directed': True, 'sep': '\t'}

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

			return MultiGraph(data = edges, keys = keys, nodes = nodes)

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
							self._graph = MultiGraph(data = ntx)
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
				self._meta_['capabilities'] = self._capabilities()		# Some capabilities depend on the content of the graph.
				self._meta_['state'] = self.states.READY.value

				break


	def get_children_idx(self, index = None):
		""" Returns the ids of the children of an id following the SourceNode interface.

		Ids are used exactly as in the .csv files that define the graph (e.g., `person|student`), without the name of the AgenticGraph in
		front. None or an empty string is the root.

		(See [`SourceNode.get_children_idx()`][mercury.graph.evidence.source_parts.SourceNode.get_children_idx].)
		"""

		if not self._is_ready('get_children_idx'):
			return None

		subtree = self._subtree(index)

		if type(subtree) is not dict:
			return None

		prefix = '' if index is None or index == '' else index + '|'

		return [prefix + key for key in subtree.keys()]


	def child(self, index):
		""" Returns the properties of the node with the given id following the SourceNode interface.

		Ids are used exactly as in the .csv files that define the graph (e.g., `person|student`), without the name of the AgenticGraph in
		front.

		(See [`SourceNode.child()`][mercury.graph.evidence.source_parts.SourceNode.child].)
		"""

		if not self._is_ready('child') or index is None or index == '':
			return None

		return self._node_properties(index)


	def _children_by_idx(self, arguments):
		""" Runs the children_by_idx capability: the children of an id with their definitions, down to "depth" levels. Returns None if
		the id does not exist and ends with TRUNCATED when there are more than max_results entries.
		"""

		index = arguments['index']

		if not self._is_ready('children_by_idx') or self._subtree(index) is _MISSING:
			return None

		budget	= {'left': self.conf.get('max_results', MAX_RESULTS), 'truncated': False}
		entries = self._entries(index, _positive_int(arguments.get('depth', 1), 1), budget)

		return entries + [TRUNCATED] if budget['truncated'] else entries


	def _entries(self, index, depth, budget):
		""" Returns the entries of the children of an id, expanded down to depth levels, spending one unit of budget per entry. All
		the siblings are listed before expanding any of them.
		"""

		entries = []
		for child in self.get_children_idx(index) or []:
			if budget['left'] == 0:
				budget['truncated'] = True
				break

			budget['left'] -= 1
			entries.append(self._described(child))

		for entry in entries:
			self._expand(entry, depth - 1, budget)

		return entries


	def _expand(self, entry, depth, budget):
		""" Adds to an entry its children down to depth levels, or marks it with "more" if it has children that are not included. """

		if type(self._subtree(entry['id'])) is not dict:
			return

		children = self._entries(entry['id'], depth, budget) if depth > 0 else []

		if len(children) > 0:
			entry['children'] = children
		else:
			entry['more'] = True


	def _node_by_idx(self, arguments):
		""" Runs the node_by_idx capability: the properties of a node and its ancestors, or None if it is not a node. """

		index		= arguments['index']
		properties	= self.child(index)

		if properties is None:
			return None

		return {'id': index, 'properties': properties, 'ancestors': self._ancestors(index)}


	def _ancestors(self, index):
		""" Returns the entries of the ancestors of an id, from its parent to the root. """

		levels = index.split('|')

		return [self._described('|'.join(levels[:n])) for n in range(len(levels) - 1, 0, -1)]


	def _described(self, index):
		""" Returns the entry of an id: the id and, if it is a node with a definition, the definition. """

		entry		= {'id': index}
		definition	= (self._node_properties(index) or {}).get('definition', None)

		if isinstance(definition, str):
			entry['definition'] = definition

		return entry


	def _search(self, arguments):
		""" Runs the search capability: the nodes whose id contains a text followed by those whose definition contains it. """

		text = str(arguments['text']).strip().lower()

		if not self._is_ready('search'):
			return None

		if text == '':
			return []

		limit = min(_positive_int(arguments.get('limit', 20), 20), self.conf.get('max_results', MAX_RESULTS))

		return self._limited([self._described(index) for index in self._matching_nodes(text)], limit)


	def _matching_nodes(self, text):
		""" Returns the ids of the nodes whose id contains text followed by those whose definition contains it, each group sorted. """

		in_id, in_definition = [], []
		for index, definition in self._graph.networkx.nodes(data = 'definition'):
			if text in index.lower():
				in_id.append(index)
			elif isinstance(definition, str) and text in definition.lower():
				in_definition.append(index)

		return sorted(in_id) + sorted(in_definition)


	def _edges(self, arguments):
		""" Runs the edges capability: the edges from or to a node, or only those of a relation and its descendants. Returns None if the
		node does not exist.
		"""

		index	 = arguments['index']
		relation = arguments.get('relation', None) or None

		if not self._is_ready('edges') or index not in self._graph.networkx.nodes:
			return None

		edges = [edge for edge in self._node_edges(index) if relation is None or descends_from(str(edge.get('relation', '')), relation)]

		return self._limited(edges, self.conf.get('max_results', MAX_RESULTS))


	def _node_edges(self, index):
		""" Returns the entries of the edges going out of or coming into a node, sorted by edge id. """

		ntx	  = self._graph.networkx
		edges = {}
		for src, dst, key, attr in list(ntx.out_edges(index, keys = True, data = True)) + list(ntx.in_edges(index, keys = True, data = True)):
			edges[(src, dst, key)] = dict({'id': key, 'src': src, 'dst': dst}, **attr)

		return sorted(edges.values(), key = lambda edge: str(edge['id']))


	def _relations_for(self, arguments):
		""" Runs the relations_for capability: the relationships a concept takes part in (by inheritance by default), sorted by id. """

		concept	  = arguments['concept']
		inherited = _as_bool(arguments.get('inherited', True))

		if not self._is_ready('relations_for'):
			return None

		entries = [self._relation_entry(index, attr, concept, inherited) for index, attr in sorted(self._graph.networkx.nodes(data = True))]

		return self._limited([entry for entry in entries if entry is not None], self.conf.get('max_results', MAX_RESULTS))


	def _relation_entry(self, index, attr, concept, inherited):
		""" Returns the entry of a relationship with the role of a concept in it, or None if the concept takes no part in it. """

		role = _role(attr, concept, inherited)

		if role is None:
			return None

		return dict({'id': index, 'src': attr['src'], 'dst': attr['dst'], 'as': role}, **self._described(index))


	def _limited(self, entries, limit):
		""" Returns at most limit entries, followed by TRUNCATED if some were left out. """

		return entries[:limit] + [TRUNCATED] if len(entries) > limit else entries


	def _is_ready(self, function):
		""" Returns True if the AgenticGraph is ready, logging an error naming the calling function if it is not. """

		if self._meta_['state'] != self.states.READY.value:
			self.log_error('AgenticGraph is not ready for %s.' % function)

			return False

		return True


	def _subtree(self, index):
		""" Returns the subtree of self._indices under an id (None for a leaf) or _MISSING if the id is not in the tree. """

		if index is None or index == '':
			return self._indices

		subtree = self._indices
		for level in index.split('|'):
			if type(subtree) is not dict or level not in subtree:
				return _MISSING

			subtree = subtree[level]

		return subtree


	def _node_properties(self, index):
		""" Returns a copy of the properties of a node or None if it does not exist. """

		nodes = self._graph.networkx.nodes

		return dict(nodes[index]) if index in nodes else None


	def close(self, endpoint_locked):
		""" Closes the AgenticGraph, persists it to disk and releases any resources it holds.

		(See [`Agentic.close()`][mercury.graph.evidence.Agentic.close].)
		"""

		if endpoint_locked and self._graph is not None and self._fname is not None:
			ntx = self._graph.networkx
			with open(self._fname, 'wb') as f:
				pickle.dump(ntx, f)

		self._graph = None


	def _add_index_to_tree(self, index):
		""" Adds an index to the hierarchical tree structure. It traverses the tree rooted at self._indices and adds dictionaries
		as required.

		Args:
			index (str): The index to add, represented as a string with components separated by '|'.
		"""

		ii = index.split('|')
		last = len(ii) - 1

		tree = self._indices

		for i, ix in enumerate(ii):
			if i == last:
				if ix not in tree:			# A parent added after its children must keep them.
					tree[ix] = None

			else:
				if ix not in tree or tree[ix] is None:
					tree[ix] = {}

				tree = tree[ix]


	def _build_indices(self):
		""" Builds the indices for the AgenticGraph for the first time after it is loaded.

		This builds a hierarchical tree structure of dictionaries, rooted at self._indices, with the ids of the nodes. Edges are not part
		of the tree.
		"""

		self._indices = {}

		for id, _ in self._graph.networkx.nodes.data('id'):
			self._add_index_to_tree(id)


	def _capabilities(self):
		""" Returns the capabilities of the AgenticGraph and sets self.call to run them.

		Some capabilities depend on the content of the graph: `edges` requires edges and `relations_for` requires nodes that declare a
		`src` and a `dst`. Before the graph is loaded, only the capabilities that do not depend on the content are returned, and they are
		set again once the graph is loaded.

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

		available = {'children_by_idx': self._children_by_idx, 'node_by_idx': self._node_by_idx, 'search': self._search}

		if self._has_edges():
			available['edges'] = self._edges

		if self._declares_relations():
			available['relations_for'] = self._relations_for

		self.call = {'%s_%s' % (name, self.name): run for name, run in available.items()}

		return [{'type': 'function', 'function': dict(name = '%s_%s' % (name, self.name), **copy.deepcopy(CAPABILITIES[name]))} for name in available]


	def _has_edges(self):
		""" Returns True if the graph is loaded and has edges. """

		return self._graph is not None and self._graph.networkx.number_of_edges() > 0


	def _declares_relations(self):
		""" Returns True if the graph is loaded and any of its nodes declares a src and a dst (like the relationships ontology). """

		if self._graph is None:
			return False

		return any(_declares(attr, 'src') and _declares(attr, 'dst') for _, attr in self._graph.networkx.nodes(data = True))
