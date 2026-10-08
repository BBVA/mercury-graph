import os, warnings

from enum import Enum

from .agentic import Agentic, AgenticRunInvalidRequest
from .agentic_graph import AgenticGraph, descends_from, parent_of


class FormalizerState(Enum):
	""" The `FormalizerState` is an enumeration that defines all possible states of a Formalizer. """

	ERR_ONTOLOGY_INIT	= -2	# Something failed loading the ontology.
	ERR_MODEL_INIT		= -1	# Something failed loading the model.

	INITIAL				=  0	# The initial state of the formalizer.
	MODEL_LOADED_OK		=  1	# The model was loaded successfully.
	ONTOLOGY_LOADED_OK	=  2	# The ontology was loaded successfully.

	READY				=  100	# The formalizer is ready to be queried.


def validate_ontologies(entities, relationships, known_ids):
	""" Checks that the three ontologies used by a Formalizer are coherent with each other.

	The checks are:

	- Every concept in `entities` and every relationship in `relationships` has its parent (the id without its last `|` level) defined
	in the same ontology.
	- Every relationship declares a `src` and a `dst` that are concepts in `entities`.
	- Every instance in `known_ids` is a name under a concept in `entities` (e.g., `person|student|Noah Kim` under `person|student`).
	- Every edge in `known_ids` has a `relation` defined in `relationships`, and the concepts of the instances it connects are the
	`src` and `dst` of that relation or descendants of them (e.g., a `person|student` can be the `src` of a relation from `person`).

	The ontologies must be loaded (piloted) before being validated. If any of them is not, that is the only problem reported.

	Args:
		entities (AgenticGraph): the entities ontology.
		relationships (AgenticGraph): the relationships ontology or None if it is disabled.
		known_ids (AgenticGraph): the known_ids ontology or None if it is disabled.

	Returns:
		(list): A list of strings, one for each problem found. It is empty if the ontologies are valid.
	"""

	ontologies = {'entities': entities, 'relationships': relationships, 'known_ids': known_ids}

	errors = _check_loaded(ontologies)
	if len(errors) > 0:
		return errors

	concepts  = set(entities._graph.networkx.nodes)
	relations = {} if relationships is None else dict(relationships._graph.networkx.nodes(data = True))

	errors += _check_parents(concepts, 'Entity', 'entities')
	errors += _check_parents(relations, 'Relationship', 'relationships')
	errors += _check_relationship_ends(relations, concepts)

	if known_ids is not None:
		errors += _check_known_instances(known_ids._graph.networkx, concepts)
		errors += _check_known_edges(known_ids._graph.networkx, relations)

	return errors


def _check_loaded(ontologies):
	""" Returns an error for every enabled ontology (a dict of name: AgenticGraph or None) that has not been loaded. """

	return ['Ontology "%s" is not loaded.' % name for name, ontology in ontologies.items() if ontology is not None and ontology._graph is None]


def _check_parents(indices, kind, ontology):
	""" Returns an error for every index whose parent is not in indices. kind and ontology name them in the messages. """

	errors = []
	for index in sorted(indices):
		if parent_of(index) is not None and parent_of(index) not in indices:
			errors.append('%s "%s" has no parent "%s" in %s.' % (kind, index, parent_of(index), ontology))

	return errors


def _check_relationship_ends(relations, concepts):
	""" Returns an error for every relationship that does not declare its src or dst, or declares one that is not a concept. """

	errors = []
	for index, attr in sorted(relations.items()):
		missing = [end for end in ('src', 'dst') if not isinstance(attr.get(end, None), str)]
		if len(missing) > 0:
			errors.append('Relationship "%s" does not declare its %s.' % (index, ' and '.join(missing)))

		for end in ('src', 'dst'):
			if end not in missing and attr[end] not in concepts:
				errors.append('Relationship "%s" has %s "%s", which is not in entities.' % (index, end, attr[end]))

	return errors


def _check_known_instances(known_ids, concepts):
	""" Returns an error for every instance in known_ids (a NetworkX graph) that is not under a concept. """

	errors = []
	for index in sorted(known_ids.nodes):
		if parent_of(index) is None:
			errors.append('Known id "%s" is not under any concept in entities.' % index)
		elif parent_of(index) not in concepts:
			errors.append('Known id "%s" is under "%s", which is not in entities.' % (index, parent_of(index)))

	return errors


def _check_known_edges(known_ids, relations):
	""" Returns the errors of every edge in known_ids (a NetworkX graph), sorted by edge key. """

	errors = []
	for src, dst, key, relation in sorted(known_ids.edges(keys = True, data = 'relation'), key = lambda edge: str(edge[2])):
		errors += _check_known_edge(src, dst, key, relation, relations)

	return errors


def _check_known_edge(src, dst, key, relation, relations):
	""" Returns the errors of one edge: a missing or unknown relation, or instances of types the relation does not connect. """

	if not isinstance(relation, str):
		return ['Known edge "%s" has no relation.' % key]

	if relation not in relations:
		return ['Known edge "%s" has relation "%s", which is not in relationships.' % (key, relation)]

	errors = []
	for end, instance in (('src', src), ('dst', dst)):
		expected = relations[relation].get(end, None)
		if parent_of(instance) is not None and isinstance(expected, str) and not descends_from(parent_of(instance), expected):
			errors.append('Known edge "%s": its %s "%s" is not a "%s" as required by "%s".' % (key, end, instance, expected, relation))

	return errors


class Formalizer(Agentic):
	""" The Formalizer is the class that takes in natural language and produces structured data in the form of subgraphs.

	## Overview

	### The Formalizer has a double role:

	1. While building the evidence graph from text in corpora, providing nodes and edges for the EvidenceGraph to be merged into a
	coherent structure.
	2. While querying the evidence graph in natural language, identifying nodes and edges in the text of a query verifying matches
	between them and corresponding nodes and edges in the evidence graph.

	### The level of "intelligence" of the Formalizer

	The Formalizer "speaks" the language of EvidenceGraph, has both an Agentic interface (to be used as a tool by an Agent or just exposed
	in an Endpoint) and direct access (via the parent) to its ontologies and from the EvidenceGraph. It also abstracts the functionality
	of some "smart" model that does the heavy lifting.

	It is smart enough to suggest potential nodes and edges or score how strongly the definition of one node matches another (making both
	actually the same entity), but the "intelligence" about how that becomes a final EvidenceGraph is handled by either an Agent or
	the EvidenceGraph itself.

	This functionality is often called (SIE) Structured Information Extracting.

	### How GLiNER2 fits into this workflow

	Unlike in the [`PdfToMarkdown`][mercury.graph.evidence.formats.PdfToMarkdown] conversion, where a lot of valid "turn-key" solutions
	exist, and therefore we do not favor any specific tool and provide a simple configuration mechanism to integrate any tool, we
	consider GLiNER2 as the mature, efficient, open-source, CPU-friendly solution for, at least, this early stage of this project.

	#### Possible alternatives to GLiNER2 could be

	- A completely LLM-based solution using a model that could reach similar performance without disproportionate computational cost.
	- A [SpaCy](https://spacy.io/) based solution for named entity recognition and relationship extraction.
	- Something like [NuExtract3](https://huggingface.co/numind/NuExtract3) which for the moment has high GPU requirements, but works
	directly from PDF (similar to [Unlimited-OCR](https://github.com/baidu/Unlimited-OCR) for the PDF stage).

	#### The functions used in GLiNER2 terms

	- **AutoExtractor** (Basic Entity Extraction): Is used for node identification form text. It is provided a schema (from a selection
	of the Ontology or custom) and the output is provided with autogenerated temporary node identifiers that require further grounding
	in the EvidenceGraph.
	- **AutoExtractor** (Structure Extraction): Is given an `extract_json()` format created by the Formalizer to match the definitions
	of both the relationship and its elements from the Ontology.
	-  **AutoExtractor** (Classification): With a classification schema provided. This is used to classify the entire text as
	containing the information or to determine if nodes belong to the same entity.

	## Ontology validation

	While piloting, the Formalizer checks that its ontologies are coherent with each other using
	[`validate_ontologies()`][mercury.graph.evidence.formalizer.validate_ontologies]. If any problem is found, every problem is logged
	and the Formalizer stops in the `ERR_ONTOLOGY_INIT` state.

	## Capabilities exposed by the Formalizer

	The Formalizer exposes three capabilities:

	1. Entity Extraction
	2. Relationship Extraction
	3. Classification

	## Known Limitations

	The functionality is still very exploratory and minimalistic. Specifically, the following limitations exist:

	- Confidence scoring is not implemented.
	- There is not mechanism to specify "threshold"
	- The key 'definition' is hardcoded, it should be included in the config to make it easier to find and modify.
	- hint_edges() requires a different logic since it is forcing to return all possible edges, not just those
	- is_a() is not implemented. It is still unclear how to merge entities and if text classification should play a role in it.

	In general, the whole system is very early-stage, released for developer use and experimentation. The best way of formalizing
	entities and relationships from text is still to be determined. It requires a functioning architecture to experiment, and that
	is what we are to-some-extent providing with this early-stage implementation.

	Args:
		schema (str): a schema (a unique name) to use for the Formalizer's ID.
		extra_args (dict): the configuration for the Formalizer.
		endpoint (Agentic): an optional Endpoint. It becomes part of the Formalizer's ID and is available via `self.endpoint`. If not
			provided, the Formalizer becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'formalizer', schema = schema, endpoint = endpoint, logger = logger)

		if schema is None:			# This allows finding out the class name (to link tools) without actually instantiating a full object.
			return

		self.states = FormalizerState

		self.conf = extra_args
		self.name = schema

		self._entities = None
		self._relation = None
		self._known_id = None
		self._model	   = None

		self._meta_ = self._meta()	# Just to make .meta reflect the initial state.


	def _run(self, request):
		""" Runs the Formalizer with the given request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""
		call = self.call.get(request['name'], None)

		if call is None:
			self.log_error('Formalizer does not have a function named "%s".' % request['name'])
			raise AgenticRunInvalidRequest

		ret = {'finish_reason': 'stop', 'message': call(request['arguments'])}

		return ret


	def _meta(self):
		""" Returns the metadata of the Formalizer.

			(See [`Agentic.meta()`][mercury.graph.evidence.Agentic.meta].)
		"""
		meta = {}
		meta['state'] = FormalizerState.INITIAL.value

		meta['description'] = self.conf.get('description', '')
		if type(meta['description']) is list:
			meta['description'] = '\n'.join(meta['description'])

		meta['capabilities'] = self._capabilities()

		return meta


	def _dry_run(self, request):
		""" Simulates running the Formalizer with the given request.

			(See [`Agentic.dry_run()`][mercury.graph.evidence.Agentic.dry_run].)

		## NOTE:

		The Endpoint takes care of validating the request according to the capabilities exposed by the Formalizer. It is not necessary to
		validate again here and the Endpoint does not forward the dry_run() request to the Formalizer. This method is provided as a
		requirement of the Agentic interface, but it is only used when you use Formalizers directly outside of an Endpoint.
		"""

		return {'status': 0, 'description': 'Valid request.'}


	def pilot(self, intent, just_once = False):
		""" Pilots the Formalizer to a new state based on the given intent.

		(See [`Agentic.pilot()`][mercury.graph.evidence.Agentic.pilot].)
		"""

		if self.meta['state'] < 0:
			self.log_error('Formalizer is in error state %d' % self._meta_['state'])

			return

		while self._meta_['state'] < intent:
			if self._meta_['state'] == self.states.INITIAL.value:
				model_config = self.conf.get('model', None)
				if model_config is None:
					self.log_error('Model configuration is missing while piloting Formalizer %s.' % self.id)

					self._meta_['state'] = self.states.ERR_MODEL_INIT.value

					break

				try:
					os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')
					os.environ.setdefault('USE_TF', '0')

					from gliner2 import AutoExtractor

				except ImportError:
					AutoExtractor = None

				library = model_config.get('library', None)
				if library != 'gliner2' or AutoExtractor is None:
					self.log_error('Missing gliner2.AutoExtractor or unsupported model library while piloting Formalizer %s.' % self.id)

					self._meta_['state'] = self.states.ERR_MODEL_INIT.value

					break

				self.AutoExtractor = AutoExtractor

				model = model_config.get('model', None)
				if model is None:
					self.log_error('Model specification is missing while piloting Formalizer %s.' % self.id)

					self._meta_['state'] = self.states.ERR_MODEL_INIT.value

					break

				map_location = model_config.get('map_location', None)
				quantize = model_config.get('quantize', None)
				compile = model_config.get('compile', None)

				args = {}
				if map_location is not None:
					args['map_location'] = map_location

				if quantize is not None:
					args['quantize'] = quantize

				if compile is not None:
					args['compile'] = compile

				try:
					with warnings.catch_warnings():
						warnings.simplefilter('ignore')
						self._model = self.AutoExtractor.from_pretrained(model, **args)

					self._meta_['state'] = self.states.MODEL_LOADED_OK.value

				except Exception as e:
					self.log_error('Failed to load model while piloting Formalizer %s: %s' % (self.id, str(e)))

					self._meta_['state'] = self.states.ERR_MODEL_INIT.value

					break

				if just_once:
					break

			if self._meta_['state'] == self.states.MODEL_LOADED_OK.value:

				graph = AgenticGraph(schema = None, extra_args = None)

				ontologies	  = self.conf.get('ontologies', None)
				endpoint_name = self.id.split('/')[0]
				graph_class	  = graph.id

				def find_tool(name):
					if ontologies is not None:
						if name not in ontologies:
							self.log_error('Ontologies is malformed in the configuration of %s (missing %s)' % (self.id, name))
							self._meta_['state'] = self.states.ERR_ONTOLOGY_INIT.value

							return None

						name = ontologies[name]

					if name is None:
						return None		# The option is just disabled via configuration

					key = '%s/%s_%s' % (endpoint_name, graph_class, name)

					if key not in self.tools:
						self.log_error('Tool with key "%s" not found while piloting Formalizer %s.' % (key, self.id))
						self._meta_['state'] = self.states.ERR_ONTOLOGY_INIT.value

						return None

					return self.tools[key]

				self._meta_['state'] = self.states.ONTOLOGY_LOADED_OK.value

				self._entities = find_tool('entities')
				self._relation = find_tool('relationships')
				self._known_id = find_tool('known_ids')

				if self._meta_['state'] < 0:
					break

				if self._entities is None:
					self.log_error('Configuration error: "entities" is mandatory while piloting Formalizer %s.' % self.id)
					self._meta_['state'] = self.states.ERR_ONTOLOGY_INIT.value

					break

				errors = validate_ontologies(self._entities, self._relation, self._known_id)

				if len(errors) > 0:
					self._handle_ontology_errors(errors)
					break

				if just_once:
					break

			if self._meta_['state'] == self.states.ONTOLOGY_LOADED_OK.value:

				def remove_capability(name):
					self._meta_['capabilities'] = [c for c in self._meta_['capabilities'] if c['function']['name'] != name]

				if self._relation is None:
					remove_capability('hint_edges_%s' % self.name)

				if self._known_id is None:
					remove_capability('is_a_%s' % self.name)

				self._meta_['state'] = self.states.READY.value

				if just_once:
					break


	def hint_nodes(self, arguments):
		""" Identifies nodes in a text from the ontology or some concepts in it.

		Args:
			arguments (dict): A dictionary containing the following keys:
				- 'text' (str): The text from which to identify nodes.
				- 'concepts' (list): A list of concepts to identify in the text. If empty, all concepts will be considered.

		Returns:
			(dict): A dictionary where keys are identified nodes and values are their descriptions.
		"""

		if self._meta_['state'] != self.states.READY.value:
			self.log_error('Formalizer is not ready for hint_nodes.')

			return None

		text = arguments.get('text', None)

		if text is None:
			self.log_error('Formalizer.hint_nodes() %s called without "text" argument.' % self.id)

			return None

		ntx = self._entities._graph.networkx
		schema = {}
		concepts = arguments.get('concepts', None)
		if concepts is None:
			for id, _ in ntx.nodes.data('id'):
				node = dict(ntx.nodes(data = True))[id]
				schema[id] = node.get('definition', '')
		else:
			for id in concepts:
				node = dict(ntx.nodes(data = True)).get(id, {})
				schema[id] = node.get('definition', '')

		schema = self._model.create_schema().entities(schema)

		result = self._model.extract(text, schema)

		return result.get('entities', {})


	def hint_edges(self, arguments):
		""" Identifies edges in a text from the ontology or some concepts in it.

		Args:
			arguments (dict): A dictionary containing the following keys:
				- 'text' (str): The text from which to identify edges.
				- 'concepts' (list): A list of concepts to identify in the text. If empty, all concepts will be considered.

		Returns:
			(dict): A dictionary where keys are identified edges and values are their descriptions.
		"""

		if self._meta_['state'] != self.states.READY.value:
			self.log_error('Formalizer is not ready for hint_edges.')

			return None

		text = arguments.get('text', None)

		if text is None:
			self.log_error('Formalizer.hint_edges() %s called without "text" argument.' % self.id)

			return None

		ntx = self._relation._graph.networkx

		format = {}
		concepts = arguments.get('concepts', None)
		if concepts is None:
			for id, _ in ntx.nodes.data('id'):
				node = dict(ntx.nodes(data = True))[id]
				src = node.get('src', None)
				dst = node.get('dst', None)
				key = node.get('definition', None)
				format[key] = [src, dst]

		else:
			for id, _ in ntx.nodes.data('id'):
				if id in concepts:
					node = dict(ntx.nodes(data = True))[id]
					src = node.get('src', None)
					dst = node.get('dst', None)
					key = node.get('definition', None)
					format[key] = [src, dst]

		result = self._model.extract_json(text, format)

		return result


	def is_a(self, arguments):
		""" Checks if a given concept is a subclass of another concept in the ontology.

		Args:
			arguments (dict): A dictionary containing the following keys:
				- 'child' (str): The child concept to check.
				- 'parent' (str): The parent concept to check against.

		Returns:
			(float): Returns a [0..1] score indicating the likelihood that the child is a subclass of the parent.
		"""

		if self._meta_['state'] != self.states.READY.value:
			self.log_error('Formalizer is not ready for is_a.')

			return None

		# TODO: Implement is_a().
		return 0


	def close(self, endpoint_locked):
		""" Closes the Formalizer, persists it to disk and releases any resources it holds.

		(See [`Agentic.close()`][mercury.graph.evidence.Agentic.close].)
		"""

		# There is no state to persist, just freeing resources.
		self._entities = None
		self._relation = None
		self._known_id = None
		self._model	   = None


	def _handle_ontology_errors(self, errors):
		""" Logs every problem found by `validate_ontologies()` and sets the `ERR_ONTOLOGY_INIT` state.

		Args:
			errors (list): The problems found, as returned by `validate_ontologies()`.
		"""

		for error in errors:
			self.log_error('Invalid ontologies in Formalizer %s: %s' % (self.id, error))

		self._meta_['state'] = self.states.ERR_ONTOLOGY_INIT.value


	def _capabilities(self):
		""" Returns the capabilities of the Formalizer.

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

		name_hint_nodes = 'hint_nodes_%s' % self.name
		name_hint_edges = 'hint_edges_%s' % self.name
		name_is_a		= 'is_a_%s' % self.name

		self.call = {name_hint_nodes: self.hint_nodes, name_hint_edges: self.hint_edges, name_is_a: self.is_a}

		return [
			{
				'type': 'function',
				'function': {
					'name': name_hint_nodes,
					'description': 'Identify nodes in a text from the ontology or some concepts in it.',
					'parameters': {
						'type': 'object',
						'properties': {
							'text': {
								'type': 'string',
								'description': 'Text from which to identify nodes.'
							},
							'concepts': {
								'type': 'array',
								'items': {
									'type': 'string'
								},
								'description': 'List of concepts to identify in the text. If empty, all concepts will be considered.'
							}
						},
						'required': ['text']
					},
					'returns': {
						'type': 'dict',
						'items': {
							'key': 'description'
						}
					}
				}
			},
			{
				'type': 'function',
				'function': {
					'name': name_hint_edges,
					'description': 'Identify edges in a text from the ontology or some concepts in it.',
					'parameters': {
						'type': 'object',
						'properties': {
							'text': {
								'type': 'string',
								'description': 'Text from which to identify edges.'
							},
							'concepts': {
								'type': 'array',
								'items': {
									'type': 'string'
								},
								'description': 'List of concepts to identify in the text. If empty, all concepts will be considered.'
							}
						},
						'required': ['text']
					},
					'returns': {
						'type': 'dict',
						'items': {
							'key': 'description'
						}
					}
				}
			},
			{
				'type': 'function',
				'function': {
					'name': name_is_a,
					'description': 'Determine if a given concept is a type of another concept in the ontology.',
					'parameters': {
						'type': 'object',
						'properties': {
							'text': {
								'type': 'string',
								'description': 'Text from which to determine the relationship between concepts.'
							},
							'concept': {
								'type': 'string',
								'description': 'The concept to check.'
							},
							'parent_concept': {
								'type': 'string',
								'description': 'The parent concept to check against.'
							}
						},
						'required': ['text', 'concept', 'parent_concept']
					},
					'returns': {
						'type': 'number',
						'description': 'A numerical score (0..1) indicating the confidence.',
						'score': {
							'type': 'number'
						}
					}
				}
			}
		]
