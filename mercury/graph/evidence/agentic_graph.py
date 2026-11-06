import os, pickle

from enum import Enum

import pandas as pd
import networkx as nx

from .agentic import Agentic, AgenticRunInvalidRequest
from mercury.graph.core import Graph


DEFAULT_FILE_FORMAT = {'src': 'src', 'dst': 'dst', 'id': 'id', 'directed': True, 'sep': '\t'}	# Every key can be set in "file_format".

MAX_RESULTS = 50		# Default maximum number of entries in the answer of a capability (configurable as "max_results").
TRUNCATED	= {'truncated': True, 'hint': 'There are more results. Ask for something more specific (a longer id or text, or a smaller depth).'}

_MISSING	= object()	# Returned by AgenticGraph._subtree() for an id that is not in the navigation tree.

LIST = {'type': 'array', 'items': {'type': 'object'}}


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


class NavigableTree:
	""" A tree of hierarchical ids (with levels separated by `|`) and the properties of each id, navigated by the capabilities of an
	AgenticGraph. For internal use of AgenticGraph only, which has one for its entities (its nodes) and one for its relationships (its
	edges).

	Its public methods answer the capabilities: they take the arguments given by an agent and return the answer, limited to max_results
	entries. Ids are levels of the tree: an id without properties (e.g., `person|student` when only `person|student|Noah` is defined) is
	a folder.

	Args:
		properties (dict): the properties of every id, as {id: {property: value}}.
		max_results (int): the maximum number of entries in an answer.
		summary (tuple): the properties that come with an id when it is listed.
	"""

	def __init__(self, properties, max_results = MAX_RESULTS, summary = ('definition',)):
		self._properties  = properties
		self._max_results = max_results
		self._summary	  = summary
		self._tree		  = AgenticGraph.tree(properties.keys())


	def children(self, index):
		""" Returns the ids of the children of an id (None or "" is the root), or None if it is a leaf or does not exist. """

		subtree = self._subtree(index)

		if type(subtree) is not dict:
			return None

		prefix = '' if index is None or index == '' else index + '|'

		return [prefix + key for key in subtree.keys()]


	def properties(self, index):
		""" Returns a copy of the properties of an id, or None if it has none (a folder or an id that does not exist). """

		return dict(self._properties[index]) if index in self._properties else None


	def ids(self):
		""" Returns every id that has properties, sorted. """

		return sorted(self._properties.keys())


	def children_by_idx(self, arguments):
		""" Answers arguments "index" and "depth": the children of an id with their summary, down to depth levels. Returns None if the id
		does not exist and ends with TRUNCATED when there are more than max_results entries.
		"""

		index = arguments['index']

		if self._subtree(index) is _MISSING:
			return None

		budget	= {'left': self._max_results, 'truncated': False}
		entries = self._entries(index, AgenticGraph.positive_int(arguments.get('depth', 1), 1), budget)

		return entries + [TRUNCATED] if budget['truncated'] else entries


	def by_idx(self, arguments):
		""" Answers argument "index": the properties of an id and its ancestors, or None if it has no properties. """

		index		= arguments['index']
		properties	= self.properties(index)

		if properties is None:
			return None

		return {'id': index, 'properties': properties, 'ancestors': self._ancestors(index)}


	def search(self, arguments):
		""" Answers arguments "text" and "limit": the ids that contain a text followed by those whose definition contains it. """

		text = str(arguments['text']).strip().lower()

		if text == '':
			return []

		limit = min(AgenticGraph.positive_int(arguments.get('limit', 20), 20), self._max_results)

		return AgenticGraph.limited([self.described(index) for index in self._matching(text)], limit)


	def described(self, index):
		""" Returns the entry of an id: the id and the properties of its summary that it has as text. """

		properties = self._properties.get(index, {})

		return dict({'id': index}, **{key: properties[key] for key in self._summary if isinstance(properties.get(key, None), str)})


	def _entries(self, index, depth, budget):
		""" Returns the entries of the children of an id, expanded down to depth levels, spending one unit of budget per entry. All
		the siblings are listed before expanding any of them.
		"""

		entries = []
		for child in self.children(index) or []:
			if budget['left'] == 0:
				budget['truncated'] = True
				break

			budget['left'] -= 1
			entries.append(self.described(child))

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


	def _ancestors(self, index):
		""" Returns the entries of the ancestors of an id, from its parent to the root. """

		levels = index.split('|')

		return [self.described('|'.join(levels[:n])) for n in range(len(levels) - 1, 0, -1)]


	def _matching(self, text):
		""" Returns the ids that contain text followed by those whose definition contains it, each group sorted. """

		in_id, in_definition = [], []
		for index, properties in self._properties.items():
			definition = properties.get('definition', None)
			if text in index.lower():
				in_id.append(index)
			elif isinstance(definition, str) and text in definition.lower():
				in_definition.append(index)

		return sorted(in_id) + sorted(in_definition)


	def _subtree(self, index):
		""" Returns the subtree under an id (None for a leaf) or _MISSING if the id is not in the tree. """

		if index is None or index == '':
			return self._tree

		subtree = self._tree
		for level in index.split('|'):
			if type(subtree) is not dict or level not in subtree:
				return _MISSING

			subtree = subtree[level]

		return subtree


class AgenticGraph(Agentic):
	""" AgenticGraph is the class that exposes a `mercury.graph.Graph` using the Agentic interface.

	## AgenticGraphs are typically persisted

	A graph is a persisted storage of anything: the storage of nodes is a key/value store with any properties. On top of that, nodes
	can be connected by edges that also have properties. AgenticGraph objects are typically persisted (that is part of their configuration
	to store such things as hierarchical ontologies for both entities and relationships). They can read from .csv files that
	contain ontologies (the keys "nodes" and "edges" of its configuration), for initialization, but do not write to .csv files to keep
	project management simple. Once the graph is initialized, it stores itself as a pickle file. When initializing the object, if the
	pickle file exists, it will be loaded rather than initializing the graph from .csv files, and a message is logged for every .csv file
	modified after the pickle was saved.

	## IDs and hierarchical structure

	The ontology is not only the place where concepts and relationships are defined to be used by the formalizer, but also the
	place where the IDs of every node and edge in the EvidenceGraph live. Despite the number of entities being potentially very large and
	AgenticGraphs typically living in RAM, the importance of creating concepts and maintaining the hierarchical structure dynamically from
	text by Agentic decisions makes this "all in one place" design recommendable. Also, the mechanism used to structure text entities using
	[`SourceNode`][mercury.graph.evidence.source_parts.SourceNode] is exactly the mechanism used in the hierarchy of the IDs.

	## How AgenticGraphs are used to build EvidenceGraphs

	There a three components:

	* The Ontology is a graph with IDs and definitions: its nodes are the types of entities and its edges the types of relationships
	between them.
	* The Formalizer takes concepts defined in the Ontology (E.g., person, product, country, etc.) also possibly relationships
	(E.g., is_owned_by, is_located_in, etc.) and finds instances of those concepts in natural language text.
	* The EvidenceGraph creates an aggregated graph of all that information handling contradictions, reinforcements and confidence.

	## What the AgenticGraph exposes via the Agentic interface

	All the internals of a graph are basically understood by the Formalizer and the EvidenceGraph. The AgenticGraph is an understandable
	storage for concepts, entity indices and relationships, and that is what is accessible via the Agentic interface. Ids are used exactly
	as in the .csv files (e.g., `person|student`), without the name of the AgenticGraph in front, and an empty id is the root:

	- `children_entities_by_idx_<name>`: the types of entity (nodes) under an id with their definitions, down to a given depth.
	- `entity_by_idx_<name>`: the properties of a type of entity and its ancestors with their definitions.
	- `search_entities_<name>`: the types of entity whose id or definition contains a text.

	Only if the graph has edges:

	- `children_relationships_by_idx_<name>`: the types of relationship (edges) under an id with their definitions, src and dst.
	- `relationship_by_idx_<name>`: the properties of a type of relationship (src, dst and definition) and its ancestors.
	- `search_relationships_<name>`: the types of relationship whose id or definition contains a text.
	- `relations_for_<name>`: the relationships a type of entity takes part in, including those of its ancestors.

	Entities and relationships are navigated in two separate trees (see `NavigableTree`). Every answer is limited to `max_results` entries
	(50 by default, configurable in `extra_args`) and ends with a truncated marker when it has been cut.

	## Known Limitations

	There is no "graph language" exposed via the Agentic interface that allows for arbitrary graph oriented queries, only the capabilities
	above. Note that Agentic
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
		""" Returns the required arguments of the capability called name (as declared in its definition) that are missing or None.

		Args:
			name (str): The full name of the capability, including the name of the graph.
			arguments (dict): The arguments supplied to the capability.

		Returns:
			(list): The names of required arguments that are missing or None; empty if none are missing or the capability is unknown.
		"""

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

		if self.meta['state'] < 0:
			self.log_error('AgenticGraph is in error state %d' % self._meta_['state'])

			return

		while self._meta_['state'] < intent:
			if self._meta_['state'] == self.states.INITIAL.value:
				try:
					self._fname = self.conf.get('persistence', None)
					if self._fname is None:
						self._graph = self._graph_from_files()
					else:
						self._fname = self._fname['path']
						parent_dir	= os.path.dirname(self._fname)

						if parent_dir:
							os.makedirs(parent_dir, exist_ok = True)

						if os.path.isfile(self._fname):
							with open(self._fname, 'rb') as f:
								ntx = pickle.load(f)			# A NetworkX graph object saved by this class.
							self._graph = MultiGraph(data = ntx)
							self._warn_about_newer_files()
						else:
							self._graph = self._graph_from_files()

				except Exception as e:
					self.log_error('Graph could not be created and initialized for AgenticGraph "%s": %s' % (self.name, e))
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

		Args:
			index (str or None): The hierarchical id of the parent; None or an empty string selects the root.

		Returns:
			(list or None): The child ids, or None if the graph is not ready, the id does not exist or it is a leaf.
		"""

		if not self._is_ready('get_children_idx'):
			return None

		return self._entities.children(index)


	def child(self, index):
		""" Returns the properties of the node with the given id following the SourceNode interface.

		Ids are used exactly as in the .csv files that define the graph (e.g., `person|student`), without the name of the AgenticGraph in
		front.

		(See [`SourceNode.child()`][mercury.graph.evidence.source_parts.SourceNode.child].)

		Args:
			index (str or None): The exact hierarchical id of the node.

		Returns:
			(dict or None): A copy of the node properties, or None if the graph is not ready or the id has no properties.
		"""

		if not self._is_ready('child') or index is None or index == '':
			return None

		return self._entities.properties(index)


	def as_argument(self):
		""" Returns the whole ontology as the argument 'ontology' of the questions of a
		[`Formalizer`][mercury.graph.evidence.Formalizer], in the order of its nodes and edges.

		Returns:
			(dict or None): 'types', a list of {'id', 'definition'}, and 'relations', a list of {'id', 'src', 'dst', 'definition'}. A
				definition that is not a text (missing or an empty cell of a .csv file) is an empty string. None if the graph is not
				loaded.
		"""

		if self._graph is None:
			return None

		ntx = self._graph.networkx

		types = []
		for index, definition in ntx.nodes(data = 'definition'):
			concept = {'id': index, 'definition': _definition_text(definition)}
			types.append(concept)

		relations = []
		for src, dst, index, definition in ntx.edges(keys = True, data = 'definition'):
			relation = {'id': index, 'src': src, 'dst': dst, 'definition': _definition_text(definition)}
			relations.append(relation)

		result = {'types': types, 'relations': relations}

		return result


	def _as_argument(self, arguments):
		""" Runs the as_argument capability (see `as_argument()`).

		Args:
			arguments (dict): No arguments.

		Returns:
			(dict or None): The whole ontology as {'types', 'relations'}, or None if not ready.
		"""

		if not self._is_ready('as_argument'):
			return None

		result = self.as_argument()

		return result


	def _children_entities_by_idx(self, arguments):
		""" Runs the children_entities_by_idx capability (see `NavigableTree.children_by_idx()`).

		Args:
			arguments (dict): The parent 'index' (str, empty for the root) and optional 'depth' (int, default 1).

		Returns:
			(list or None): The children with their summaries and nested children, ending with TRUNCATED if limited; None if not ready
				or the id does not exist.
		"""

		if not self._is_ready('children_entities_by_idx'):
			return None

		return self._entities.children_by_idx(arguments)


	def _entity_by_idx(self, arguments):
		""" Runs the entity_by_idx capability (see `NavigableTree.by_idx()`).

		Args:
			arguments (dict): The exact entity id as 'index' (str).

		Returns:
			(dict or None): The entity 'id', 'properties' and 'ancestors', or None if not ready or the id has no properties.
		"""

		if not self._is_ready('entity_by_idx'):
			return None

		return self._entities.by_idx(arguments)


	def _search_entities(self, arguments):
		""" Runs the search_entities capability (see `NavigableTree.search()`).

		Args:
			arguments (dict): The search 'text' (str) and optional 'limit' (int, default 20, capped by max_results).

		Returns:
			(list or None): Matching entities with their summaries, ending with TRUNCATED if limited, or None if not ready.
		"""

		if not self._is_ready('search_entities'):
			return None

		return self._entities.search(arguments)


	def _children_relationships_by_idx(self, arguments):
		""" Runs the children_relationships_by_idx capability (see `NavigableTree.children_by_idx()`).

		Args:
			arguments (dict): The parent 'index' (str, empty for the root) and optional 'depth' (int, default 1).

		Returns:
			(list or None): The children with their summaries and nested children, ending with TRUNCATED if limited; None if not ready
				or the id does not exist.
		"""

		if not self._is_ready('children_relationships_by_idx'):
			return None

		return self._relationships.children_by_idx(arguments)


	def _relationship_by_idx(self, arguments):
		""" Runs the relationship_by_idx capability (see `NavigableTree.by_idx()`).

		Args:
			arguments (dict): The exact relationship id as 'index' (str).

		Returns:
			(dict or None): The relationship 'id', 'properties' and 'ancestors', or None if not ready or the id has no properties.
		"""

		if not self._is_ready('relationship_by_idx'):
			return None

		return self._relationships.by_idx(arguments)


	def _search_relationships(self, arguments):
		""" Runs the search_relationships capability (see `NavigableTree.search()`).

		Args:
			arguments (dict): The search 'text' (str) and optional 'limit' (int, default 20, capped by max_results).

		Returns:
			(list or None): Matching relationships with their summaries, ending with TRUNCATED if limited, or None if not ready.
		"""

		if not self._is_ready('search_relationships'):
			return None

		return self._relationships.search(arguments)


	def _relations_for(self, arguments):
		""" Runs the relations_for capability: the relationships a type of entity takes part in (by inheritance by default), sorted by id.

		Args:
			arguments (dict): The entity type as 'concept' (str) and optional 'inherited' (bool or str, default True): include the relationships
				declared for its ancestors.

		Returns:
			(list or None): Relationships with their summaries and the entity type's role, ending with TRUNCATED if limited; None if
				not ready.
		"""

		if not self._is_ready('relations_for'):
			return None

		concept	  = arguments['concept']
		inherited = self._as_bool(arguments.get('inherited', True))
		entries	  = [self._relation_entry(index, concept, inherited) for index in self._relationships.ids()]

		return self.limited([entry for entry in entries if entry is not None], self.conf.get('max_results', MAX_RESULTS))


	def _relation_entry(self, index, concept, inherited):
		""" Returns the entry of a relationship with the role of a type of entity in it, or None if it takes no part in it.

		Args:
			index (str): The exact id of the relationship.
			concept (str): The hierarchical id of the entity type.
			inherited (bool): Whether the entity type also takes part where its ancestors do.

		Returns:
			(dict or None): The relationship 'id', 'src', 'dst', summary and role ('as'), or None if the entity type takes no part.
		"""

		attr = self._relationships.properties(index)
		role = self._role(attr, concept, inherited)

		if role is None:
			return None

		return dict({'id': index, 'src': attr['src'], 'dst': attr['dst'], 'as': role}, **self._relationships.described(index))


	def _is_ready(self, function):
		""" Returns True if the AgenticGraph is ready, logging an error naming the calling function if it is not.

		Args:
			function (str): The name of the calling function, included in the error message.

		Returns:
			(bool): True if the graph is ready, False otherwise.
		"""

		if self._meta_['state'] != self.states.READY.value:
			self.log_error('AgenticGraph is not ready for %s.' % function)

			return False

		return True


	def close(self, endpoint_locked):
		""" Closes the AgenticGraph, persists it to disk and releases any resources it holds.

		(See [`Agentic.close()`][mercury.graph.evidence.Agentic.close].)
		"""

		if endpoint_locked and self._graph is not None and self._fname is not None:
			ntx = self._graph.networkx
			with open(self._fname, 'wb') as f:
				pickle.dump(ntx, f)

		self._graph = None


	def _graph_from_files(self):
		""" Returns the graph built from the files of nodes and edges in the configuration.

		Returns:
			(MultiGraph): The graph loaded from the configured files, or an empty graph if no files are configured.
		"""

		return self.graph_from_files(self.conf.get('nodes', None), self.conf.get('edges', None), self.conf.get('file_format', None))


	def _warn_about_newer_files(self):
		""" Logs a message for every file of nodes or edges modified after the pickle was saved, since loading the pickle ignores it. """

		for kind in ('nodes', 'edges'):
			spec = self.conf.get(kind, None)
			if spec is not None and os.path.isfile(spec['path']) and os.path.getmtime(spec['path']) > os.path.getmtime(self._fname):
				self.log_message('"%s" changed after "%s" was saved, so its changes are not loaded. Delete "%s" to load them.' %
								 (spec['path'], self._fname, self._fname))


	def _build_indices(self):
		""" Builds the two navigable trees of the AgenticGraph after it is loaded: one with the ids of its nodes (the entities) and one
		with the ids of its edges (the relationships), whose properties include their src and dst.
		"""

		ntx			= self._graph.networkx
		max_results = self.conf.get('max_results', MAX_RESULTS)
		relations	= {key: dict(attr, src = src, dst = dst) for src, dst, key, attr in ntx.edges(keys = True, data = True)}

		self._entities		= NavigableTree(dict(ntx.nodes(data = True)), max_results)
		self._relationships = NavigableTree(dict(sorted(relations.items())), max_results, ('definition', 'src', 'dst'))


	def _capabilities(self):
		""" Returns the capabilities of the AgenticGraph and sets self.call to run them.

		The capabilities of relationships require edges. Before the graph is loaded, only those of entities are returned, and the
		capabilities are set again once the graph is loaded.

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

		available = {'children_entities_by_idx': self._children_entities_by_idx, 'entity_by_idx': self._entity_by_idx,
					 'search_entities': self._search_entities, 'as_argument': self._as_argument}

		if self._has_edges():
			available.update({'children_relationships_by_idx': self._children_relationships_by_idx, 'relationship_by_idx':
							  self._relationship_by_idx, 'search_relationships': self._search_relationships, 'relations_for': self._relations_for})

		self.call = {'%s_%s' % (name, self.name): run for name, run in available.items()}

		return [{'type': 'function', 'function': dict(name = '%s_%s' % (name, self.name), **self._named(CAPABILITIES[name], self.name))} for name in available]


	def _has_edges(self):
		""" Returns True if the graph is loaded and has edges.

		Returns:
			(bool): True if the graph is loaded and contains at least one edge, False otherwise.
		"""

		return self._graph is not None and self._graph.networkx.number_of_edges() > 0


	@staticmethod
	def parent_of(index):
		""" Returns the parent of a hierarchical id (the id without its last `|` level) or None if it has a single level.

		Args:
			index (str): The hierarchical id, with levels separated by '|'.

		Returns:
			(str or None): The id without its last level, or None if it has a single level.
		"""

		return index.rsplit('|', 1)[0] if '|' in index else None


	@staticmethod
	def descends_from(concept, ancestor):
		""" Returns True if concept is ancestor or one of its descendants in the `|` hierarchy (person_group does not descend from person).

		Args:
			concept (str): The hierarchical id to check.
			ancestor (str): The hierarchical id of the possible ancestor.

		Returns:
			(bool): True if concept equals ancestor or starts with ancestor followed by '|', False otherwise.
		"""

		return concept == ancestor or concept.startswith(ancestor + '|')


	@staticmethod
	def positive_int(value, default):
		""" Returns value as an integer if it is (or is text for) a number greater than zero and default otherwise.

		Args:
			value (object): The value to convert to an integer.
			default (int): The fallback when conversion raises TypeError or ValueError, or the converted value is not positive.

		Returns:
			(int): The positive converted integer, or default.
		"""

		try:
			return int(value) if int(value) > 0 else default

		except (TypeError, ValueError):
			return default


	@staticmethod
	def _as_bool(value):
		""" Returns False for False or a text such as "false", "no" or "0" and True for anything else.

		Args:
			value (object): The value whose stripped, lowercase string representation is checked.

		Returns:
			(bool): False for 'false', 'no' or '0' after normalization, True otherwise.
		"""

		return str(value).strip().lower() not in ('false', 'no', '0')


	@staticmethod
	def _role(attr, concept, inherited):
		""" Returns the role ('src', 'dst' or 'both') of a type of entity in a relationship given its attributes, or None if it takes no part.
		With inherited, a type of entity also takes part where one of its ancestors does.

		Args:
			attr (dict): The relationship attributes, including 'src' and 'dst' entity type ids.
			concept (str): The hierarchical id of the entity type.
			inherited (bool): Whether matching an ancestor of concept also counts as taking part.

		Returns:
			(str or None): 'src', 'dst' or 'both' for the matching ends, or None if neither end matches.
		"""

		roles = [end for end in ('src', 'dst') if (AgenticGraph.descends_from(concept, attr[end]) if inherited else concept == attr[end])]

		if len(roles) == 0:
			return None

		return roles[0] if len(roles) == 1 else 'both'


	@staticmethod
	def parameters(required, **properties):
		""" Returns the JSON schema of the parameters of a capability.

		Args:
			required (list): The names of the required parameters.
			**properties (dict): Parameter names mapped to their JSON schema definitions.

		Returns:
			(dict): An object schema with 'type', 'properties' and 'required'.
		"""

		return {'type': 'object', 'properties': properties, 'required': required}


	@staticmethod
	def _named(value, name):
		""" Returns a copy of a capability definition with {name} replaced by the name of the AgenticGraph in every text.

		Args:
			value (object): A capability definition or nested value; dictionaries and lists are traversed recursively.
			name (str): The graph name to substitute for '{name}' in string values.

		Returns:
			(object): A copied dictionary or list, a substituted string, or the original value for other types.
		"""

		if isinstance(value, dict):
			return {key: AgenticGraph._named(item, name) for key, item in value.items()}

		if isinstance(value, list):
			return [AgenticGraph._named(item, name) for item in value]

		return value.replace('{name}', name) if isinstance(value, str) else value


	@staticmethod
	def graph_from_files(nodes = None, edges = None, file_format = None):
		""" Returns a MultiGraph built from a file of nodes and a file of edges (empty if there are none).

		Every id must be unique, and every src and dst of the edges must be one of the nodes. Edges cannot be loaded without nodes.

		Args:
			nodes (dict): the optional file of nodes, a dictionary with a "type" ("csv" or "pickle") and a "path".
			edges (dict): the optional file of edges, like nodes.
			file_format (dict): the optional names of the columns ("src", "dst" and "id"), "directed" and the separator ("sep") of the .csv
				files. Every key left out takes its default value.

		Returns:
			(MultiGraph): the graph.
		"""

		keys = {**DEFAULT_FILE_FORMAT, **(file_format or {})}

		nodes = AgenticGraph._read_table(nodes, keys['sep'])
		edges = AgenticGraph._read_table(edges, keys['sep'])

		if nodes is not None:
			AgenticGraph._check_unique_ids(nodes, keys, 'Nodes')

		if edges is None:
			edges = AgenticGraph._no_edges(keys)
		else:
			AgenticGraph._check_edge_ends(nodes, edges, keys)
			AgenticGraph._check_unique_ids(edges, keys, 'Edges')

		return MultiGraph(data = edges, keys = keys, nodes = nodes)


	@staticmethod
	def _read_table(spec, sep):
		""" Returns the pandas DataFrame described by spec (a "type" and a "path"), or None if there is no spec.

		Args:
			spec (dict or None): The file 'type' ('csv' or 'pickle') and 'path', or None when no file is specified.
			sep (str): The separator to use when reading a CSV file; ignored for pickle files.

		Returns:
			(pandas.DataFrame or None): The loaded table, or None if spec is None.
		"""

		if spec is None:
			return None

		if spec['type'] == 'csv':
			return pd.read_csv(spec['path'], sep = sep)

		if spec['type'] == 'pickle':
			return pd.read_pickle(spec['path'])

		raise ValueError('Unsupported file type "%s".' % spec['type'])


	@staticmethod
	def _check_unique_ids(table, keys, kind):
		""" Raises a ValueError listing every id that is repeated in table (the nodes or the edges, as named by kind).

		Without this check, NetworkX would silently merge repeated nodes (and edges with the same ends), keeping the last attributes.

		Args:
			table (pandas.DataFrame): The table of nodes or edges to check.
			keys (dict): The file format mapping whose 'id' value names the identifier column.
			kind (str): The name of the table, such as 'Nodes' or 'Edges', used in the error message.
		"""

		ids		 = table[keys['id']]
		repeated = ids[ids.duplicated()].unique()

		if len(repeated) > 0:
			raise ValueError('%s have repeated ids: %s.' % (kind, ', '.join('"%s"' % index for index in repeated)))


	@staticmethod
	def _check_edge_ends(nodes, edges, keys):
		""" Raises a ValueError if there are no nodes or if any src or dst of the edges is not one of them (all are listed at once).

		Without this check, NetworkX would silently create a node, without any attributes, for every undeclared src or dst.

		Args:
			nodes (pandas.DataFrame or None): The declared nodes, or None when no file of nodes was supplied.
			edges (pandas.DataFrame): The edges whose ends must be declared nodes.
			keys (dict): The file format mapping naming the 'id', 'src' and 'dst' columns.
		"""

		if nodes is None:
			raise ValueError('Edges cannot be loaded without a file of nodes.')

		undeclared = AgenticGraph._undeclared_ends(set(nodes[keys['id']]), edges, keys)

		if len(undeclared) > 0:
			raise ValueError('Edges refer to nodes that are not declared: %s.' % ', '.join(undeclared))


	@staticmethod
	def _undeclared_ends(declared, edges, keys):
		""" Returns a description of every src or dst of the edges that is not in declared, e.g. '"c" (dst of "e1")'.

		Args:
			declared (set): The ids of the declared nodes.
			edges (pandas.DataFrame): The edges to check.
			keys (dict): The file format mapping naming the 'id', 'src' and 'dst' columns.

		Returns:
			(list): Descriptions of undeclared ends, each naming the missing node, its role and its edge id.
		"""

		undeclared = []
		for _, row in edges.iterrows():
			for end in ('src', 'dst'):
				if row[keys[end]] not in declared:
					undeclared.append('"%s" (%s of "%s")' % (row[keys[end]], end, row[keys['id']]))

		return undeclared


	@staticmethod
	def _no_edges(keys):
		""" Returns an empty DataFrame of edges with just the column headers required by a graph.

		Args:
			keys (dict): The file format mapping naming the 'src' and 'dst' columns.

		Returns:
			(pandas.DataFrame): An empty table with string-typed source and destination columns.
		"""

		return pd.DataFrame({keys['src']: pd.Series(dtype = 'str'), keys['dst']: pd.Series(dtype = 'str')})


	@staticmethod
	def tree(ids):
		""" Returns the tree of nested dictionaries of hierarchical ids: every level is a key whose value is the dictionary of its children,
		or None if it has none.

		Args:
			ids (iterable): The hierarchical string ids, with levels separated by '|'.

		Returns:
			(dict): The nested dictionaries of id levels, with None for leaves.
		"""

		tree = {}
		for index in ids:
			AgenticGraph._add_to_tree(tree, index.split('|'))

		return tree


	@staticmethod
	def _add_to_tree(tree, levels):
		""" Adds the levels of an id to a tree, creating the dictionaries it needs. A parent added after its children keeps them.

		Args:
			tree (dict): The tree to update in place.
			levels (list): The nonempty list of string levels of an id.
		"""

		for level in levels[:-1]:
			if tree.get(level, None) is None:
				tree[level] = {}

			tree = tree[level]

		if levels[-1] not in tree:
			tree[levels[-1]] = None


	@staticmethod
	def limited(entries, limit):
		""" Returns at most limit entries, followed by TRUNCATED if some were left out.

		Args:
			entries (list): The entries to return in their current order.
			limit (int): The maximum number of entries to keep before the optional truncation marker.

		Returns:
			(list): The entries, or their first limit items followed by TRUNCATED when some were left out.
		"""

		return entries[:limit] + [TRUNCATED] if len(entries) > limit else entries


def _definition_text(value):
	""" Returns a definition if it is a text, or an empty string otherwise (missing, or NaN from an empty cell of a .csv file). """

	if isinstance(value, str):
		return value

	return ''


CAPABILITIES = {
	'children_entities_by_idx': {
		'description': 'List the types of entity under an id in the ontology "{name}", with their definitions. Ids are hierarchical, with '
					   'levels separated by "|" (e.g., "parent|child"). Use "" to list the top level and depth to see several levels at once. '
					   'Entries with "more": true have children of their own.',
		'parameters': AgenticGraph.parameters(
			['index'],
			index = {'type': 'string', 'description': 'Exact id, with levels separated by "|" (e.g., "parent|child"). Use "" for the top level.'},
			depth = {'type': 'integer', 'description': 'Number of levels to go down. Defaults to 1.'}
		),
		'returns': LIST
	},
	'entity_by_idx': {
		'description': 'Read a type of entity of the ontology "{name}" by its exact id: its properties, such as its definition, and its '
					   'ancestors, which tell what kind of thing it is. Returns null if the id is not a type of entity; use '
					   'search_entities_{name} to find ids.',
		'parameters': AgenticGraph.parameters(
			['index'],
			index = {'type': 'string', 'description': 'Exact id of the type of entity, with levels separated by "|" (e.g., "parent|child").'}
		),
		'returns': {'type': 'object'}
	},
	'search_entities': {
		'description': 'Find the types of entity of the ontology "{name}" whose id or definition contains a text, ignoring case. Use it '
					   'first when you do not know the exact id.',
		'parameters': AgenticGraph.parameters(
			['text'],
			text  = {'type': 'string', 'description': 'Text to find, such as a name or a word of a definition.'},
			limit = {'type': 'integer', 'description': 'Maximum number of results. Defaults to 20.'}
		),
		'returns': LIST
	},
	'as_argument': {
		'description': 'Get the whole ontology "{name}" as the argument "ontology" of the questions of a Formalizer (extract_nodes, '
					   'match_node and extract_edges): its types of entity and of relationship, with their definitions. Pass it unchanged '
					   'as "ontology", or leave out the types and relationships you do not want the Formalizer to look for.',
		'parameters': AgenticGraph.parameters([]),
		'returns': {'type': 'object', 'description': '"types", a list of {"id", "definition"}, and "relations", a list of {"id", "src", '
												   '"dst", "definition"}.'}
	},
	'children_relationships_by_idx': {
		'description': 'List the types of relationship under an id in the ontology "{name}", with their definitions and the types of entity '
					   'they connect (src and dst). Ids are hierarchical, with levels separated by "|" (e.g., "parent|child"). Use "" to '
					   'list the top level and depth to see several levels at once. Entries with "more": true have children of their own.',
		'parameters': AgenticGraph.parameters(
			['index'],
			index = {'type': 'string', 'description': 'Exact id, with levels separated by "|" (e.g., "parent|child"). Use "" for the top level.'},
			depth = {'type': 'integer', 'description': 'Number of levels to go down. Defaults to 1.'}
		),
		'returns': LIST
	},
	'relationship_by_idx': {
		'description': 'Read a type of relationship of the ontology "{name}" by its exact id: its properties (the types of entity it '
					   'connects, src and dst, and its definition) and its ancestors. Returns null if the id is not a type of relationship; '
					   'use search_relationships_{name} to find ids.',
		'parameters': AgenticGraph.parameters(
			['index'],
			index = {'type': 'string', 'description': 'Exact id of the type of relationship, with levels separated by "|" (e.g., '
													  '"parent|child").'}
		),
		'returns': {'type': 'object'}
	},
	'search_relationships': {
		'description': 'Find the types of relationship of the ontology "{name}" whose id or definition contains a text, ignoring case. Use '
					   'it first when you do not know the exact id.',
		'parameters': AgenticGraph.parameters(
			['text'],
			text  = {'type': 'string', 'description': 'Text to find, such as a verb or a word of a definition.'},
			limit = {'type': 'integer', 'description': 'Maximum number of results. Defaults to 20.'}
		),
		'returns': LIST
	},
	'relations_for': {
		'description': 'Get the types of relationship that a type of entity can take part in according to the ontology "{name}", and '
					   'whether it is their source (src), destination (dst) or both. Includes those of its ancestors unless inherited is '
					   'false.',
		'parameters': AgenticGraph.parameters(
			['concept'],
			concept	  = {'type': 'string', 'description': 'Exact id of a type of entity, with levels separated by "|" (e.g., "parent|child").'},
			inherited = {'type': 'boolean', 'description': 'Include the relationships declared for the ancestors of the type of entity. '
														   'Defaults to true.'}
		),
		'returns': LIST
	}
}
