import os, re, unicodedata, warnings

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


def validate_ontology(ontology):
	""" Checks that an ontology (entities as nodes and relationships as edges between them) is coherent.

	The checks are:

	- Every entity has its parent (the id without its last `|` level) defined.
	- Every relationship has its parent defined (e.g., `works_on` for `works_on|leads`).
	- The `src` and `dst` of a relationship are those of its parent or descendants of them (e.g., `works_on|leads` can go from
	`person|student` if `works_on` goes from `person`).

	That ids are unique and that the `src` and `dst` of every relationship are entities of the ontology is already checked when it is
	loaded (see
	[`graph_from_files()`][mercury.graph.evidence.agentic_graph.graph_from_files]).

	Args:
		ontology (AgenticGraph): the ontology. It must be loaded (piloted) before being validated, otherwise that is the only problem
			reported.

	Returns:
		(list): A list of strings, one for each problem found. It is empty if the ontology is valid.
	"""

	if ontology._graph is None:
		return ['Ontology "%s" is not loaded.' % ontology.name]

	ntx		  = ontology._graph.networkx
	relations = _relation_ends(ntx)

	errors  = _check_parents(set(ntx.nodes), 'Entity', ontology.name)
	errors += _check_parents(set(relations), 'Relationship', ontology.name)
	errors += _check_relation_inheritance(relations)

	return errors


def validate_initial_graph(ntx, ontology):
	""" Checks that an initial graph of instances (such as the one an EvidenceGraph starts from) matches an ontology.

	The checks are:

	- Every instance is a name under a type of entity of the ontology (e.g., `person|student|Noah Kim` under `person|student`).
	- Every edge has a `relation` that is a relationship of the ontology, and the types of the instances it connects are the `src` and
	`dst` of that relationship or descendants of them (e.g., a `person|student` can be the `src` of a relationship from `person`).

	Args:
		ntx (networkx.MultiDiGraph): the initial graph, with the instances as nodes and their relationships as edges.
		ontology (AgenticGraph): the ontology. It must be loaded.

	Returns:
		(list): A list of strings, one for each problem found. It is empty if the initial graph is valid.
	"""

	types	  = set(ontology._graph.networkx.nodes)
	relations = _relation_ends(ontology._graph.networkx)

	return _check_instances(ntx, types) + _check_instance_edges(ntx, relations)


def _check_instances(ntx, types):
	""" Returns an error for every instance in ntx that is not under a type of entity in types. """

	errors = []
	for index in sorted(ntx.nodes):
		if parent_of(index) is None:
			errors.append('Instance "%s" has no type: its id must start with a type of entity of the ontology.' % index)
		elif parent_of(index) not in types:
			errors.append('Instance "%s" is of type "%s", which is not in the ontology.' % (index, parent_of(index)))

	return errors


def _check_instance_edges(ntx, relations):
	""" Returns the errors of every edge in ntx, sorted by edge id. """

	errors = []
	for src, dst, key, relation in sorted(ntx.edges(keys = True, data = 'relation'), key = lambda edge: str(edge[2])):
		errors += _check_instance_edge(src, dst, key, relation, relations)

	return errors


def _check_instance_edge(src, dst, key, relation, relations):
	""" Returns the errors of one edge: a missing or unknown relation, or instances of types the relation does not connect. """

	if not isinstance(relation, str):
		return ['Edge "%s" has no relation.' % key]

	if relation not in relations:
		return ['Edge "%s" has relation "%s", which is not in the ontology.' % (key, relation)]

	errors = []
	for end, instance, expected in zip(('src', 'dst'), (src, dst), relations[relation]):
		if parent_of(instance) is not None and not descends_from(parent_of(instance), expected):
			errors.append('Edge "%s": its %s "%s" is not a "%s" as required by "%s".' % (key, end, instance, expected, relation))

	return errors


def _relation_ends(ntx):
	""" Returns a dictionary of relationship id: (src, dst) of the ontology ntx. """

	return {key: (src, dst) for src, dst, key in ntx.edges(keys = True)}


def _check_relation_inheritance(relations):
	""" Returns an error for every src or dst of a relationship that is not that of its parent or a descendant of it. """

	errors = []
	for index, ends in sorted(relations.items()):
		parent = parent_of(index)
		if parent in relations:
			errors += _check_inherited_ends(index, ends, parent, relations[parent])

	return errors


def _check_inherited_ends(index, ends, parent, parent_ends):
	""" Returns an error for each end of a relationship that does not descend from the same end of its parent. """

	errors = []
	for end, concept, expected in zip(('src', 'dst'), ends, parent_ends):
		if not descends_from(concept, expected):
			errors.append('Relationship "%s" has %s "%s", which is not a "%s" as required by its parent "%s".' % (index, end, concept, expected, parent))

	return errors


def _check_parents(indices, kind, ontology):
	""" Returns an error for every index whose parent is not in indices. kind and ontology name them in the messages. """

	errors = []
	for index in sorted(indices):
		if parent_of(index) is not None and parent_of(index) not in indices:
			errors.append('%s "%s" has no parent "%s" in %s.' % (kind, index, parent_of(index), ontology))

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
	in an Endpoint) and direct access (via the parent) to its ontology and from the EvidenceGraph. It also abstracts the functionality
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

	While piloting, the Formalizer checks that its ontology is coherent using
	[`validate_ontology()`][mercury.graph.evidence.formalizer.validate_ontology]. If any problem is found, every problem is logged
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

	IGNORED_WORDS = ['mr', 'mrs', 'ms', 'miss', 'dr', 'prof']	# Default "ignored_words": titles left out when comparing names.

	def __init__(self, schema, extra_args, endpoint = None, logger = None):
		super().__init__(my_class = 'formalizer', schema = schema, endpoint = endpoint, logger = logger)

		if schema is None:			# This allows finding out the class name (to link tools) without actually instantiating a full object.
			return

		self.states = FormalizerState

		self.conf = extra_args
		self.name = schema

		self._ontology = None
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
				self._ontology = self._find_ontology()

				if self._ontology is None:
					self._meta_['state'] = self.states.ERR_ONTOLOGY_INIT.value
					break

				errors = validate_ontology(self._ontology)

				if len(errors) > 0:
					self._handle_ontology_errors(errors)
					break

				self._meta_['state'] = self.states.ONTOLOGY_LOADED_OK.value

				if just_once:
					break

			if self._meta_['state'] == self.states.ONTOLOGY_LOADED_OK.value:
				self._meta_['state'] = self.states.READY.value

				if just_once:
					break


	def _create_schema(self, arguments):
		ntx = self._ontology._graph.networkx
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
		return schema


	def hint_nodes(self, arguments):
		""" Identifies nodes in a text from the ontology or some concepts in it.

		Args:
			arguments (dict): A dictionary containing the following keys:
				- 'text' (str): The text from which to identify nodes.
				- 'concepts' (list): A list of concepts to identify in the text. If empty, all concepts will be considered.
				- 'candidates' (list): The ids of the known instances a mention can be. If missing, no mention has candidates.

		Returns:
			(list): One dictionary per mention with 'mention' (the text as it appears), 'type' (the most specific of the types found for
				it that are compatible with the most confident one), 'confidence' (that of the type) and 'candidates'.

				The candidates of a mention are those of its root type that share a word with it, as {'id', 'score'}, from the highest to
				the lowest score. The score is the share of words in common (1.0 when all of them are), leaving out the words of both types,
				possessives, accents and the "ignored_words" of the configuration (titles by default). A candidate whose type is neither
				an ancestor nor a descendant of the type of the mention has 'type_conflict' True. The score measures how alike the names
				are, not whether they are the same instance: that is decided by the caller.
		"""

		if self._meta_['state'] != self.states.READY.value:
			self.log_error('Formalizer is not ready for hint_nodes.')
			return None

		text = arguments.get('text', None)
		if text is None:
			self.log_error('Formalizer.hint_nodes() %s called without "text" argument.' % self.id)
			return None

		schema	   = self._create_schema(arguments)
		extraction = self._model.extract(text, schema, include_confidence = True)

		entities   = extraction.get('entities', {})
		candidates = arguments.get('candidates', [])
		result	   = self._resolve_mentions(entities, candidates)

		return result


	def _resolve_mentions(self, entities, candidates):
		""" Returns one node per mention in the entities found by the model, with a single type and its candidates. """

		confidences_by_mention = self._group_types_by_mention(entities)

		result = [self._resolve_mention(mention, confidences, candidates) for mention, confidences in confidences_by_mention.items()]

		return result


	def _group_types_by_mention(self, entities):
		""" Returns {mention: {type: confidence}} from the entities found by the model ({type: [{'text': ..., 'confidence': ...}]}).

		A mention found more than once with the same type keeps its highest confidence.
		"""

		found = {}
		for concept, matches in entities.items():
			for match in matches:
				confidences = found.setdefault(match['text'], {})
				confidences[concept] = max(match['confidence'], confidences.get(concept, 0))

		return found


	def _resolve_mention(self, mention, confidences, candidates):
		""" Returns the node of a mention: its text, its chosen type, the confidence of that type and its candidates. """

		concept = self._choose_type(confidences)
		found	= self._find_candidates(mention, concept, candidates)
		node	= {'mention': mention, 'type': concept, 'confidence': confidences[concept], 'candidates': found}

		return node


	def _choose_type(self, confidences):
		""" Returns the most specific type compatible with the most confident one (it, its ancestors or its descendants).

		Among equally specific types, the most confident is chosen. Types of other branches are discarded.
		"""

		anchor	   = max(confidences, key = confidences.get)
		compatible = [concept for concept in confidences if descends_from(concept, anchor) or descends_from(anchor, concept)]

		result = max(compatible, key = lambda concept: (concept.count('|'), confidences[concept]))

		return result


	def _find_candidates(self, mention, concept, candidates):
		""" Returns the candidates of the root type of concept that share a word with the mention, from the highest to the lowest score. """

		same_root = [candidate for candidate in candidates if self._have_same_root(concept, parent_of(candidate))]
		scored	  = [self._score_candidate(mention, concept, candidate) for candidate in same_root]
		found	  = [candidate for candidate in scored if candidate['score'] > 0]

		result = sorted(found, key = lambda candidate: candidate['score'], reverse = True)

		return result


	def _have_same_root(self, concept, known_type):
		""" Returns True if both types are under the same root type (person|teacher and person|student are). """

		if known_type is None:
			return False

		return concept.split('|')[0] == known_type.split('|')[0]


	def _score_candidate(self, mention, concept, candidate):
		""" Returns {'id', 'score'} of a candidate for a mention, with 'type_conflict' if their types are in different branches. """

		known_type = parent_of(candidate)
		generic	   = self._get_words(concept) | self._get_words(known_type)

		words	   = self._get_significant_words(mention, generic)
		name_words = self._get_significant_words(candidate.rsplit('|', 1)[1], generic)
		score	   = self._jaccard(words, name_words)
		scored	   = {'id': candidate, 'score': score}

		if not (descends_from(concept, known_type) or descends_from(known_type, concept)):
			scored['type_conflict'] = True

		return scored


	def _get_significant_words(self, name, generic):
		""" Returns the words of a name without possessives, the generic words (those of the types) and the ignored words. """

		without_possessives = re.sub("['’]s\\b", '', name)
		ignored = set(self.conf.get('ignored_words', self.IGNORED_WORDS))

		result = self._get_words(without_possessives) - generic - ignored

		return result


	def _get_words(self, text):
		""" Returns the set of lowercase words of a text, without accents (`|` and `_` separate words). """

		decomposed = unicodedata.normalize('NFKD', text.lower())
		plain	   = ''.join(char for char in decomposed if not unicodedata.combining(char))

		result = set(re.findall('[^\\W_]+', plain))

		return result


	def _jaccard(self, words, other_words):
		""" Returns the share of words in common between two sets of words (0 if both are empty). """

		every = words | other_words

		if len(every) == 0:
			return 0

		result = len(words & other_words)/len(every)

		return result


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

		ntx = self._ontology._graph.networkx

		format = {}
		concepts = arguments.get('concepts', None)
		for src, dst, id, definition in ntx.edges(keys = True, data = 'definition'):
			if concepts is None or id in concepts:
				format[definition] = [src, dst]

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
		self._ontology = None
		self._model	   = None


	def _find_ontology(self):
		""" Returns the AgenticGraph named by "ontology" in the configuration among the tools, or None (logging why) if it is not found. """

		name = self.conf.get('ontology', None)

		if name is None:
			self.log_error('Configuration error: "ontology" is mandatory while piloting Formalizer %s.' % self.id)

			return None

		key = '%s/%s_%s' % (self.id.split('/')[0], AgenticGraph(schema = None, extra_args = None).id, name)

		if key not in self.tools:
			self.log_error('Tool with key "%s" not found while piloting Formalizer %s.' % (key, self.id))

			return None

		return self.tools[key]


	def _handle_ontology_errors(self, errors):
		""" Logs every problem found by `validate_ontology()` and sets the `ERR_ONTOLOGY_INIT` state.

		Args:
			errors (list): The problems found, as returned by `validate_ontology()`.
		"""

		for error in errors:
			self.log_error('Invalid ontology in Formalizer %s: %s' % (self.id, error))

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
							},
							'candidates': {
								'type': 'array',
								'items': {
									'type': 'string'
								},
								'description': 'Ids of the known instances a mention can be. If missing, no mention has candidates.'
							}
						},
						'required': ['text']
					},
					'returns': {
						'type': 'array',
						'items': {
							'type': 'object',
							'description': 'One node per mention, with "mention", "type", "confidence" and "candidates" ({"id", "score"}).'
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
