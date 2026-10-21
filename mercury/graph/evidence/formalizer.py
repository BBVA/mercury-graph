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
	- **AutoExtractor** (Relation Extraction): `extract_relations()` gives (head, tail) pairs. It is only asked for the relationships
	with the same type at both ends, whose structure cannot tell one end from the other.
	Whether two nodes are the same instance ([`is_same_node()`][mercury.graph.evidence.Formalizer.is_same_node]) is not asked to
	GLiNER2: it is scored comparing their names.

	## Ontology validation

	While piloting, the Formalizer checks that its ontology is coherent using
	[`validate_ontology()`][mercury.graph.evidence.formalizer.validate_ontology]. If any problem is found, every problem is logged
	and the Formalizer stops in the `ERR_ONTOLOGY_INIT` state.

	## Capabilities exposed by the Formalizer

	The Formalizer exposes three capabilities:

	1. Entity Extraction (`hint_nodes`): every mention of a type of the ontology, with the known instances it can be.
	2. Relationship Extraction (`hint_edges`): every edge of a relationship of the ontology between the nodes found in a text.
	3. Node comparison (`is_same_node`): how likely two nodes (known instances or mentions) are the same instance.

	## Linking mentions to known instances

	[`link_mention()`][mercury.graph.evidence.Formalizer.link_mention] decides whether a mention found by `hint_nodes` is a known
	instance, a new one or ambiguous, asking `is_same_node` when the name alone is not enough. It is not a capability: those rules
	belong to the caller (the EvidenceGraph) and are here until it uses them.

	## Known Limitations

	The functionality is still very exploratory and minimalistic. Specifically, the following limitations exist:

	- Confidence scoring is not implemented.
	- There is not mechanism to specify "threshold"
	- The key 'definition' is hardcoded, it should be included in the config to make it easier to find and modify.
	- is_same_node() only compares the names in the ids: it ignores the texts of the nodes.

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

	IGNORED_WORDS		= ['mr', 'mrs', 'ms', 'miss', 'dr', 'prof']	# Default "ignored_words": titles left out when comparing names.
	SAME_NODE_THRESHOLD = 0.3	# Default "same_node_threshold": the is_same_node() score from which link_mention() accepts a candidate.

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

		mention_id = '%s|%s' % (concept, mention)
		scored	   = [self._score_candidate(mention_id, candidate) for candidate in candidates]
		found	   = [candidate for candidate in scored if candidate['score'] > 0]

		result = sorted(found, key = lambda candidate: candidate['score'], reverse = True)

		return result


	def _score_candidate(self, mention_id, candidate):
		""" Returns {'id', 'score'} of a candidate for a mention, with 'type_conflict' if their types are in different branches. """

		concept	   = parent_of(mention_id)
		known_type = parent_of(candidate)
		score	   = self._compare_names(mention_id, candidate)
		scored	   = {'id': candidate, 'score': score}

		if known_type is not None and not (descends_from(concept, known_type) or descends_from(known_type, concept)):
			scored['type_conflict'] = True

		return scored


	def _compare_names(self, index, other):
		""" Returns the share of significant words in common between the names of two ids, or 0 if their types have different roots. """

		concept		  = parent_of(index)
		other_concept = parent_of(other)
		if not self._have_same_root(concept, other_concept):
			return 0

		generic		= self._get_words(concept) | self._get_words(other_concept)
		words		= self._get_significant_words(index.rsplit('|', 1)[1], generic)
		other_words = self._get_significant_words(other.rsplit('|', 1)[1], generic)

		result = self._jaccard(words, other_words)

		return result


	def _have_same_root(self, concept, other_concept):
		""" Returns True if both types are under the same root type (person|teacher and person|student are). """

		if concept is None or other_concept is None:
			return False

		return concept.split('|')[0] == other_concept.split('|')[0]


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
		""" Identifies edges of the ontology, or of some relationships in it, between the nodes of a text.

		The model is asked for every relationship as a structure with a field for each end, named by its type. A relationship whose
		ends have the same type (e.g., place to place) has two fields with the same name, so the model only finds that the relationship
		is in the text, not its pairs: the model is then asked again, only for those relationships, for (head, tail) pairs.

		The mentions at both ends are replaced by the ids of the nodes, and the edges are kept if both ends are nodes with an id and
		their types are those of the relationship or descendants of them. A repeated edge keeps its highest confidence, and an edge is
		dropped when the same pair has an edge of a more specific relationship (e.g., works_on when works_on|leads is found).

		Unlike `hint_nodes`, which is given the known instances as candidates, `hint_edges` is given the nodes already linked: it must be
		called after `hint_nodes` and `link_mention()` on the same text. Whether an edge is already known is not part of its output:
		once both ends are ids, that is an exact lookup in the graph, and what to do with it (confirm, aggregate or contradict) is
		decided by the EvidenceGraph.

		Args:
			arguments (dict): A dictionary containing the following keys:
				- 'text' (str): The text from which to identify edges.
				- 'nodes' (list): The nodes of the text, with 'mention' and 'id' (as returned by `link_mention()`).
				- 'concepts' (list): The ids of the relationships to identify. If missing, all of them are considered.

		Returns:
			(list): One dictionary per edge with 'src', 'relation', 'dst' (ids) and 'confidence'.
		"""

		if self._meta_['state'] != self.states.READY.value:
			self.log_error('Formalizer is not ready for hint_edges.')

			return None

		text  = arguments.get('text', None)
		nodes = arguments.get('nodes', None)

		if text is None or nodes is None:
			self.log_error('Formalizer.hint_edges() %s called without "text" and "nodes" arguments.' % self.id)

			return None

		relations = self._get_relations(arguments.get('concepts', None))
		ids		  = {node['mention']: node['id'] for node in nodes}

		found	  = self._extract_structures(text, relations)
		triples	  = self._pair_mentions(found, relations, ids)
		same_type = self._find_same_type_relations(found, relations)

		if len(same_type) > 0:
			triples += self._extract_directed_pairs(text, same_type, relations, ids)

		result = self._finish_edges(triples, relations)

		return result


	def _get_relations(self, concepts):
		""" Returns {id: (src, dst, definition)} of the relationships of the ontology, or of those in concepts. """

		ntx = self._ontology._graph.networkx

		relations = {}
		for src, dst, index, definition in ntx.edges(keys = True, data = 'definition'):
			if concepts is None or index in concepts:
				relations[index] = (src, dst, definition)

		return relations


	def _extract_structures(self, text, relations):
		""" Returns {relation id: matches} found by the model, every relationship asked as a structure named by its definition. """

		structures = {definition: [src, dst] for src, dst, definition in relations.values()}
		extraction = self._model.extract_json(text, structures, include_confidence = True)

		by_definition = {definition: index for index, (_, _, definition) in relations.items()}
		result		  = {by_definition[definition]: matches for definition, matches in extraction.items()}

		return result


	def _pair_mentions(self, found, relations, ids):
		""" Returns (src id, relation, dst id, confidence) for every pair of mentions of the matches of relations with different end types. """

		triples = []
		for index, matches in found.items():
			src_type, dst_type, _ = relations[index]
			if src_type != dst_type:
				for match in matches:
					triples += self._pair_match(index, match.get(src_type, []), match.get(dst_type, []), ids)

		return triples


	def _pair_match(self, index, sources, destinations, ids):
		""" Returns a triple for every source and destination mention of one match, with the lowest of both confidences. """

		triples = []
		for src in sources:
			for dst in destinations:
				confidence = min(src['confidence'], dst['confidence'])
				triples.append((ids.get(src['text'], None), index, ids.get(dst['text'], None), confidence))

		return triples


	def _find_same_type_relations(self, found, relations):
		""" Returns the ids of the relationships with the same type at both ends that the model found mentions of. """

		result = []
		for index, matches in found.items():
			src_type, dst_type, _ = relations[index]
			mentions = [span for match in matches for spans in match.values() for span in spans]
			if src_type == dst_type and len(mentions) > 0:
				result.append(index)

		return result


	def _extract_directed_pairs(self, text, same_type, relations, ids):
		""" Returns (src id, relation, dst id, confidence) for every (head, tail) pair the model finds for the given relationships. """

		schema = {index: relations[index][2] for index in same_type}
		found  = self._model.extract_relations(text, schema, include_confidence = True)

		triples = []
		for index, pairs in found.get('relation_extraction', {}).items():
			for pair in pairs:
				src = ids.get(pair['head']['text'], None)
				dst = ids.get(pair['tail']['text'], None)
				triples.append((src, index, dst, pair['head']['confidence']))

		return triples


	def _finish_edges(self, triples, relations):
		""" Returns the edges of the triples with valid ends, without repeated edges or edges of a relationship more generic than another. """

		valid = [triple for triple in triples if self._has_valid_ends(triple, relations)]
		best  = self._keep_highest_confidence(valid)

		result = []
		for (src, index, dst), confidence in best.items():
			if not self._has_more_specific_edge(src, index, dst, best):
				result.append({'src': src, 'relation': index, 'dst': dst, 'confidence': confidence})

		return result


	def _has_valid_ends(self, triple, relations):
		""" Returns True if both ends have an id whose type is that of the relationship or a descendant of it. """

		src, index, dst, _ = triple
		src_type, dst_type, _ = relations[index]

		if src is None or dst is None:
			return False

		return descends_from(parent_of(src), src_type) and descends_from(parent_of(dst), dst_type)


	def _keep_highest_confidence(self, triples):
		""" Returns {(src, relation, dst): confidence} with the highest confidence of every repeated edge. """

		best = {}
		for src, index, dst, confidence in triples:
			best[(src, index, dst)] = max(confidence, best.get((src, index, dst), 0))

		return best


	def _has_more_specific_edge(self, src, index, dst, edges):
		""" Returns True if the same pair has an edge of a relationship that descends from index. """

		for other_src, other_index, other_dst in edges:
			if (other_src, other_dst) == (src, dst) and other_index != index and descends_from(other_index, index):
				return True

		return False


	def is_same_node(self, arguments):
		""" Scores how likely two nodes are the same instance. It is symmetric.

		A node is a known instance or a mention, whose id is its type followed by the mention (e.g., `person|teacher|Ms. Ruiz`). This
		Formalizer only compares the names in the ids, as `hint_nodes` does with its candidates: 0 if their types have different roots
		and the share of significant words in common otherwise. The texts are accepted for Formalizers that read them.

		Args:
			arguments (dict): A dictionary containing the following keys:
				- 'node' (dict): A node, with 'id' (str) and optionally 'texts' (list), the texts that mention it.
				- 'other' (dict): The other node, in the same format.

		Returns:
			(float): A score in [0..1], or None if the Formalizer is not ready or a node is missing.
		"""

		if self._meta_['state'] != self.states.READY.value:
			self.log_error('Formalizer is not ready for is_same_node.')

			return None

		node  = arguments.get('node', None)
		other = arguments.get('other', None)

		if node is None or other is None:
			self.log_error('Formalizer.is_same_node() %s called without "node" and "other" arguments.' % self.id)

			return None

		result = self._compare_names(node['id'], other['id'])

		return result


	def link_mention(self, node, text = None):
		""" Decides whether a mention found by `hint_nodes` is a known instance, a new one or ambiguous.

		1. Candidates with `type_conflict` are discarded unless their score is 1 (the whole name).
		2. A single candidate with score 1 is the instance.
		3. Otherwise, `is_same_node` scores the mention (with the text) against every candidate left, and those from the configured
		"same_node_threshold" on are kept.

		Args:
			node (dict): A node returned by `hint_nodes`.
			text (str): The text where the mention was found, passed to `is_same_node`.

		Returns:
			(dict): The 'mention' with its 'id' and 'status': 'known' (with 'type_conflict' True if the type found contradicts the known
				one), 'new' (its type followed by the mention) or 'ambiguous' (id None, with the ids of the instances it can be in
				'candidates').
		"""

		viable = [candidate for candidate in node['candidates'] if candidate['score'] == 1 or not candidate.get('type_conflict', False)]
		whole  = [candidate for candidate in viable if candidate['score'] == 1]

		accepted = whole if len(whole) == 1 else self._confirm_candidates(node, viable, text)
		result	 = self._build_link(node, accepted)

		return result


	def _confirm_candidates(self, node, candidates, text):
		""" Returns the candidates that is_same_node scores from the configured threshold on as the same instance as the mention. """

		threshold = self.conf.get('same_node_threshold', self.SAME_NODE_THRESHOLD)
		texts	  = [] if text is None else [text]
		mention	  = {'id': '%s|%s' % (node['type'], node['mention']), 'texts': texts}

		result = []
		for candidate in candidates:
			score = self.is_same_node({'node': mention, 'other': candidate})
			if score >= threshold:
				result.append(candidate)

		return result


	def _build_link(self, node, accepted):
		""" Returns the decision for a mention given the candidates accepted: new if none, known if one and ambiguous if several. """

		if len(accepted) == 0:
			index = '%s|%s' % (node['type'], node['mention'])
			link  = {'mention': node['mention'], 'id': index, 'status': 'new'}
		elif len(accepted) == 1:
			link = {'mention': node['mention'], 'id': accepted[0]['id'], 'status': 'known'}
			if accepted[0].get('type_conflict', False):
				link['type_conflict'] = True
		else:
			ids	 = [candidate['id'] for candidate in accepted]
			link = {'mention': node['mention'], 'id': None, 'status': 'ambiguous', 'candidates': ids}

		return link


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
		name_is_same	= 'is_same_node_%s' % self.name

		self.call = {name_hint_nodes: self.hint_nodes, name_hint_edges: self.hint_edges, name_is_same: self.is_same_node}

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
					'description': 'Identify edges of the ontology, or of some relationships in it, between the nodes of a text.',
					'parameters': {
						'type': 'object',
						'properties': {
							'text': {
								'type': 'string',
								'description': 'Text from which to identify edges.'
							},
							'nodes': {
								'type': 'array',
								'items': {
									'type': 'object'
								},
								'description': 'The nodes of the text, with "mention" and "id".'
							},
							'concepts': {
								'type': 'array',
								'items': {
									'type': 'string'
								},
								'description': 'Ids of the relationships to identify. If missing, all of them are considered.'
							}
						},
						'required': ['text', 'nodes']
					},
					'returns': {
						'type': 'array',
						'items': {
							'type': 'object',
							'description': 'One edge with "src", "relation", "dst" (ids) and "confidence".'
						}
					}
				}
			},
			{
				'type': 'function',
				'function': {
					'name': name_is_same,
					'description': 'Score how likely two nodes (known instances or mentions, as "type|name" ids) are the same instance.',
					'parameters': {
						'type': 'object',
						'properties': {
							'node': {
								'type': 'object',
								'description': 'A node: "id" and optionally "texts", a list of texts that mention it.'
							},
							'other': {
								'type': 'object',
								'description': 'The other node, in the same format.'
							}
						},
						'required': ['node', 'other']
					},
					'returns': {
						'type': 'number',
						'description': 'A score (0..1): how likely both nodes are the same instance.'
					}
				}
			}
		]
