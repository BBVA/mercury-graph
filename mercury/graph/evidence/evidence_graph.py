import os, pickle

import pandas as pd
import networkx as nx

from .agentic import Agentic, AgenticRunInvalidRequest
from .source import Source
from .agentic_graph import GraphState, MultiGraph
from .formalizer import Formalizer
from .agent import Agent


class EvidenceGraph(Agentic):
	""" The EvidenceGraph is the class that holds the knowledge about one or many sources in the form of a graph.

	## Overview

	This is the core of the architecture.

	It is essentially a multigraph, whose nodes and edges are strictly connected by their ids to ontologies and hold
	information about all the sources that contain every mention to the entities and relationships represented in it
	and evidence metrics associated with each piece of information.

	It delegates, but ultimately controls, its own building process. It pilots itself only up to a point where all its
	tools are ready to be queried and previous persisted state is loaded, but piloting does not include processing
	all the sources available to it. That is done by ordering it to crawl from a starting source id.

	It is the structured memory where the knowledge (defined and limited to by the concepts in the ontology	that created
	the nodes and edges) is stored.

	It is available for:

	- Inspection and correction via deterministic (create, read, update, delete) operations
	- Aggregation of more evidence as a continuous process
	- Integration with upstream and downstream Agentic components

	## Storing the graph

	The EvidenceGraph is a child of `Agentic` directly, not `AgenticGraph`. It does contain a `MultiGraph` to store the data just like
	`AgenticGraph` does. There are enough differences (initialization, capabilities, much larger size) and the commonalities are mostly
	contained in the class `MultiGraph` which both use to justify this decision.

	The graph is persisted to disk using a pickle file and a configuration mechanism identical to that of `AgenticGraph`.

	## Connection to ontologies is via the Formalizer

	An `EvidenceGraph` is connected to exactly one `Formalizer`. The tasks themselves the Formalizer does (`id_nodes` identifying nodes,
	`id_edges` identifying edges and `is_same` determining identity and category membership) are treated as separate functionality to
	make it possible to have them handled by an Agent or an agent that supervises another Agentic, etc.

	The `Formalizer` must have its three ontology `AgenticGraph` objects (entities, relationships, known_ids) defined. And the
	`EvidenceGraph`	will modify these ontology objects as it integrates new evidence into the graph. It is highly recommended not to share
	these `AgenticGraph` ontology objects with other `EvidenceGraph` instances.

	## Extraction of candidate entities and relationships

	Extraction of candidate entities is controlled via the `"id_nodes"` configuration key that must provide the name of an `Agentic` object
	usable as a tool. In this early implementation, the `"id_nodes"` tool is expected to be the `Formalizer` itself, any replacement should
	provide	a compatible capability.

	The `EvidenceGraph` provides a similar key `"id_edges"`, which must also expect a capability compatible with the corresponding capability
	in the `Formalizer` that still requires research to provide a reliable implementation.

	## Merging of entities and relationships inside the EvidenceGraph

	Those are two different problems that are currently handled by the same functionality in the Formalizer.

	It is currently managed as a text classification with definitions that are not yet fully formalized. Expect this to change.

	### Evidence weighting and contradiction handling

	The EvidenceGraph must compute aggregated evidence weights for both entities and relationships. This is a function of

	- an authority score for each source
	- a confidence score that the relationship or entity is correctly attributed to the given text.
	- a confidence measure of the correct identification of the entities involved in the relationship.

	aggregated over each chunk of evidence.

	## Building the entire EvidenceGraph from Sources

	This is done by "crawling" the sources. The mechanism is similar to "reading" by a human, instead of training over the entire corpus.
	We intentionally, want the system be able to manage the situation where the sources are immense and "reading" everything would
	require an impractical amount of time and resources to be handled gracefully.

	In the case of large corpora, like wikipedia, it is possible to parse them at a high level, just extracting top level titles, index
	those and their corresponding embeddings. The Sources provide that functionality. It is still an open problem to determine how
	"answering a question" can have a budget of resources allocated to read new content in the source and become more knowledgeable
	as a continuous process and not just as a static snapshot of a trained model.

	## Downstream Agentic Integration

	For now, we are researching ways to enforce functionality that is not well supported in the Formalizer (GLiNER2) to be done by Agents.
	Agents, as currently implemented, should be flexible enough to provide functionality compatible with that of the Formalizer, although
	at a much higher computational cost. Expect this to evolve as the integration between Agents and the Formalizer matures.

	## Capabilities (Upstream Agentic Integration)

	The first capability implemented is the ability to crawl a source, extracting all the text content, formalizing it and aggregating it.
	The full implementation of this capability requires proper entity and relationship recognition and aggregation mechanisms.

	The EvidenceGraph, once it can reliably aggregate evidence, should not provide any "guessing" functionality, it must strictly
	behave like a database providing functionality to create, read, update, and delete entities and relationships by a supervisor to
	maintain quality EvidenceGraph as valuable data assets.

	## Querying EvidenceGraph

	The EvidenceGraph is defined as much by what it does as by what **it does not do**: **It does not answer queries in natural language.**
	It is just a multigraph with downstream solution to gather text and formalize it into structured evidence.

	To answer questions about the content of the EvidenceGraph, we use a specialized Agent. The Agent has access to: the EvidenceGraph,
	the Formalizer and the Sources that the EvidenceGraph has. The Agent can use the Formalizer to identify the entities and relationships
	in the query and relate them to the ontologies defined in the EvidenceGraph, possibly including user confirmation.

	Finding the best way to query the EvidenceGraph through the Agent is an ongoing research topic.

	## Known Limitations

	- This class lacks the merging mechanism for both entities and relationships.
	- The size of the EvidenceGraph is limited by the current implementation to a NetworkX multigraph that fits in memory.
	- Some mechanism that allows distributing the computation of one large EvidenceGraph across multiple machines will be necessary.
	- The full implementation of the Source crawling functionality requires the missing mechanisms.
	- Continuous and incomplete (as in the percentage of the source that has been crawled) knowledge acquisition is still an open challenge.

	Args:
		schema (str): a schema (a unique name) to use for the EvidenceGraph's ID.
		extra_args (dict): the configuration for the EvidenceGraph.
		endpoint (Agentic): an optional Endpoint. It becomes part of the EvidenceGraph's ID and is available via `self.endpoint`. If not
			provided, the EvidenceGraph becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'evidence_graph', schema = schema, endpoint = endpoint, logger = logger)

		if schema is None:			# This allows finding out the class name (to link tools) without actually instantiating a full object.
			return

		self.states = GraphState

		self.conf = extra_args
		self.name = schema

		self._graph	= None

		self._formalizer = None

		self._entities = None
		self._relation = None
		self._known_id = None

		self._id_nodes = None
		self._id_edges = None
		self._is_same  = None

		self._sources = None

		self._meta_ = self._meta()	# Just to make .meta reflect the initial state.


	def _run(self, request):
		""" Runs the EvidenceGraph with the given request.

		(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""

		call = self.call.get(request['name'], None)

		if call is None:
			self.log_error('EvidenceGraph does not have a function named "%s".' % request['name'])
			raise AgenticRunInvalidRequest

		index = request['arguments'].get('index', None)

		if index is None:
			self.log_error('EvidenceGraph function "%s" requires an "index" argument.' % request['name'])
			raise AgenticRunInvalidRequest

		ret = {'finish_reason': 'stop', 'message': call(index)}

		return ret


	def _meta(self):
		""" Returns the metadata of the EvidenceGraph.

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
		""" Simulates running the EvidenceGraph with the given request.

			(See [`Agentic.dry_run()`][mercury.graph.evidence.Agentic.dry_run].)

		## NOTE:

		The Endpoint takes care of validating the request according to the capabilities exposed by the EvidenceGraph. It is not necessary to
		validate again here and the Endpoint does not forward the dry_run() request to the EvidenceGraph. This method is provided as a
		requirement of the Agentic interface, but it is only used when you use Formalizers directly outside of an Endpoint.
		"""

		return {'status': 0, 'description': 'Valid request.'}


	def pilot(self, intent, just_once = False):
		""" Pilots the EvidenceGraph to a new state based on the given intent.

		(See [`Agentic.pilot()`][mercury.graph.evidence.Agentic.pilot].)
		"""

		def new_graph():
			""" Creates an empty new graph when there is no persisted graph to load. The pandas dataframes are empty with just
			column headers as required by a nx.digraph. The class `MultiGraph` overrides the behavior and converts it into a multigraph.
			"""

			keys = {'src': 'src', 'dst': 'dst', 'id': 'id', 'directed': True, 'sep': '\t'}

			nodes = pd.DataFrame({keys['id']: pd.Series(dtype='str')})

			edges = pd.DataFrame({keys['src']: pd.Series(dtype='str'), keys['dst']: pd.Series(dtype='str')})

			return MultiGraph(data = edges, keys = keys, nodes = nodes)

		if self.meta['state'] < 0:
			self.log_error('EvidenceGraph is in error state %d' % self._meta_['state'])

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
					self.log_error('Graph could not be created and initialized for EvidenceGraph "%s".' % self.name)
					self._meta_['state'] = self.states.ERR_GRAPH_INIT.value
					break

				self._meta_['state'] = self.states.GRAPH_LOADED_OK.value

				if just_once:
					break

			if self._meta_['state'] == self.states.GRAPH_LOADED_OK.value:
				if self._connect_downstream():
					self._meta_['state'] = self.states.READY.value

				else:
					self._meta_['state'] = self.states.ERR_BUILDING.value

				break


	def crawl(self, index):
		# TODO: Implement the crawl functionality for the EvidenceGraph.
	def _connect_downstream(self):
		""" Connects the EvidenceGraph to downstream components or systems.

		This parses the configuration and locates every necessary downstream Agentic: the Formalizer, its ontologies, Agentics with
		capabilities to do entity extraction, etc. and the Sources.

		Returns:
			(bool): True if the connection was successful, False otherwise.
		"""

		agentics = self.conf.get('agentics', None)

		if agentics is None:
			self.log_error('No agentics configuration found in EvidenceGraph "%s".' % self.name)

			return False

		try:
			formalizer	= agentics['formalizer']

			assert type(formalizer) is str and formalizer != ''

			id_nodes = agentics['id_nodes']
			id_edges = agentics['id_edges']
			is_same	 = agentics['is_same']
			sources	 = agentics['sources']

			if type(sources) is not list:
				assert type(sources) is str
				sources = [sources]

		except:
			self.log_error('Error parsing agentics configuration in EvidenceGraph "%s".' % self.name)

			return False

		endpoint_name = self.id.split('/')[0]

		ag = Formalizer(schema = None, extra_args = None)
		class_name_formalizer = ag.id

		key = '%s/%s_%s' % (endpoint_name, class_name_formalizer, formalizer)

		if key not in self.tools:
			self.log_error('Formalizer "%s" not found in tools for EvidenceGraph "%s".' % (formalizer, self.name))

			return False

		self._formalizer = self.tools[key]

		self._entities = self._formalizer._entities
		self._relation = self._formalizer._relation
		self._known_id = self._formalizer._known_id

		ag = Agent(schema = None, extra_args = None)
		class_name_agent = ag.id

		def get_tool(name):
			key = '%s/%s_%s' % (endpoint_name, class_name_formalizer, name)

			if key in self.tools:
				return self.tools[key]

			key = '%s/%s_%s' % (endpoint_name, class_name_agent, name)
			if key in self.tools:
				return self.tools[key]

			return None

		if id_nodes is not None:
			self._id_nodes = get_tool(id_nodes)

			if self._id_nodes is None:
				self.log_error('"id_nodes" tool "%s" not found for EvidenceGraph "%s".' % (id_nodes, self.name))
				return False

		if id_edges is not None:
			self._id_edges = get_tool(id_edges)

			if self._id_edges is None:
				self.log_error('"id_edges" tool "%s" not found for EvidenceGraph "%s".' % (id_edges, self.name))
				return False

		if is_same is not None:
			self._is_same = get_tool(is_same)

			if self._is_same is None:
				self.log_error('"is_same" tool "%s" not found for EvidenceGraph "%s".' % (is_same, self.name))
				return False

		ag = Source(schema = None, extra_args = None)
		class_name_source = ag.id

		self._sources = []
		for source in sources:
			key = '%s/%s_%s' % (endpoint_name, class_name_source, source)

			if key in self.tools:
				self._sources.append(self.tools[key])
			else:
				self.log_error('"sources" tool "%s" not found for EvidenceGraph "%s".' % (source, self.name))
				return False

		return True


	def close(self, endpoint_locked):
		""" Closes the EvidenceGraph, persists it to disk and releases any resources it holds.

		(See [`Agentic.close()`][mercury.graph.evidence.Agentic.close].)
		"""

		if endpoint_locked and self._graph is not None and self._fname is not None:
			ntx = self._graph.networkx
			with open(self._fname, 'wb') as f:
				pickle.dump(ntx, f)

		self._graph	= None

		self._formalizer = None

		self._id_nodes = None
		self._id_edges = None
		self._is_same  = None

		self._sources = None


	def _capabilities(self):
		""" Returns the capabilities of the EvidenceGraph.

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

		name_crawl = 'crawl_%s' % self.name

		self.call = {name_crawl: self.crawl}

		return [
			{
				'type': 'function',
				'function': {
					'name': name_crawl,
					'description': 'Crawl the text starting from a given source index.',
					'parameters': {
						'type': 'object',
						'properties': {
							'index': {
								'type': 'string',
								'description': 'Source index from which to start crawling the text.'
							}
						},
						'required': ['index']
					},
					'returns': {
						'type': 'dict',
						'items': {
							'key': 'description'
						}
					}
				}
			}
		]
