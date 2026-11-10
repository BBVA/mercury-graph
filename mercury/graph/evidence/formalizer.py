from enum import Enum

from .agentic import Agentic, AgenticRunInvalidRequest
from .agentic_graph import AgenticGraph
from .decider import RulesDecider
from .gliner_deciders import GlinerEdgesDecider, GlinerNodesDecider
from .question import Question


DECIDERS = {												# The Decider of every "decider" name in the configuration of a question.
	'rules':		RulesDecider,
	'gliner_nodes': GlinerNodesDecider,
	'gliner_edges': GlinerEdgesDecider
}

ARGUMENT_TYPES = {'string': str, 'array': list, 'object': dict, 'number': (int, float)}	# The Python type of every JSON type of an argument.


class FormalizerState(Enum):
	""" The `FormalizerState` is an enumeration that defines all possible states of a Formalizer. """

	ERR_DECIDER_INIT	= -1	# Something failed loading the deciders.

	INITIAL				=  0	# The initial state of the formalizer.

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
	[`AgenticGraph.graph_from_files()`][mercury.graph.evidence.AgenticGraph.graph_from_files]).

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
	""" Checks that an initial graph of instances (such as the one an EvidenceGraph starts from) matches an ontology and describes
	every instance.

	The checks are those of [`validate_instances()`][mercury.graph.evidence.formalizer.validate_instances] and:

	- Every instance has a `description` that is not empty (e.g., "A science teacher at Riverside High School.").

	Args:
		ntx (networkx.MultiDiGraph): the initial graph, with the instances as nodes and their relationships as edges.
		ontology (AgenticGraph): the ontology. It must be loaded.

	Returns:
		(list): A list of strings, one for each problem found. It is empty if the initial graph is valid.
	"""

	errors	= validate_instances(ntx, ontology)
	errors += _check_descriptions(ntx)

	return errors


def validate_instances(ntx, ontology):
	""" Checks that a graph of instances matches an ontology.

	The checks are:

	- Every instance is a name under a type of entity of the ontology (e.g., `person|student|Noah Kim` under `person|student`).
	- Every edge has a `relation` that is a relationship of the ontology, and the types of the instances it connects are the `src` and
	`dst` of that relationship or descendants of them (e.g., a `person|student` can be the `src` of a relationship from `person`).

	Args:
		ntx (networkx.MultiDiGraph): the graph, with the instances as nodes and their relationships as edges.
		ontology (AgenticGraph): the ontology. It must be loaded.

	Returns:
		(list): A list of strings, one for each problem found. It is empty if the graph matches the ontology.
	"""

	types	  = set(ontology._graph.networkx.nodes)
	relations = _relation_ends(ontology._graph.networkx)

	return _check_instances(ntx, types) + _check_instance_edges(ntx, relations)


def _check_descriptions(ntx):
	""" Returns an error for every instance in ntx without a description or with an empty one. """

	errors = []
	for index, description in sorted(ntx.nodes(data = 'description')):
		if not _is_text(description):
			errors.append('Instance "%s" has no description: the initial graph needs one for every instance.' % index)

	return errors


def _is_text(value):
	""" Returns True if value is a string that is not empty or only spaces (an empty cell of a .csv file is read as NaN). """

	if not isinstance(value, str):
		return False

	return value.strip() != ''


def _check_instances(ntx, types):
	""" Returns an error for every instance in ntx that is not under a type of entity in types. """

	errors = []
	for index in sorted(ntx.nodes):
		if AgenticGraph.parent_of(index) is None:
			errors.append('Instance "%s" has no type: its id must start with a type of entity of the ontology.' % index)
		elif AgenticGraph.parent_of(index) not in types:
			errors.append('Instance "%s" is of type "%s", which is not in the ontology.' % (index, AgenticGraph.parent_of(index)))

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
		if AgenticGraph.parent_of(instance) is not None and not AgenticGraph.descends_from(AgenticGraph.parent_of(instance), expected):
			errors.append('Edge "%s": its %s "%s" is not a "%s" as required by "%s".' % (key, end, instance, expected, relation))

	return errors


def _relation_ends(ntx):
	""" Returns a dictionary of relationship id: (src, dst) of the ontology ntx. """

	return {key: (src, dst) for src, dst, key in ntx.edges(keys = True)}


def _check_relation_inheritance(relations):
	""" Returns an error for every src or dst of a relationship that is not that of its parent or a descendant of it. """

	errors = []
	for index, ends in sorted(relations.items()):
		parent = AgenticGraph.parent_of(index)
		if parent in relations:
			errors += _check_inherited_ends(index, ends, parent, relations[parent])

	return errors


def _check_inherited_ends(index, ends, parent, parent_ends):
	""" Returns an error for each end of a relationship that does not descend from the same end of its parent. """

	errors = []
	for end, concept, expected in zip(('src', 'dst'), ends, parent_ends):
		if not AgenticGraph.descends_from(concept, expected):
			errors.append('Relationship "%s" has %s "%s", which is not a "%s" as required by its parent "%s".' % (index, end, concept, expected, parent))

	return errors


def _check_parents(indices, kind, ontology):
	""" Returns an error for every index whose parent is not in indices. kind and ontology name them in the messages. """

	errors = []
	for index in sorted(indices):
		if AgenticGraph.parent_of(index) is not None and AgenticGraph.parent_of(index) not in indices:
			errors.append('%s "%s" has no parent "%s" in %s.' % (kind, index, AgenticGraph.parent_of(index), ontology))

	return errors



class Formalizer(Agentic):
	""" The Formalizer is the class that takes in natural language and produces structured data in the form of subgraphs.

	## Overview

	### The Formalizer has a double role:

	1. While building the evidence graph from text in corpora, providing nodes and edges for the EvidenceGraph to be merged into a
	coherent structure.
	2. While querying the evidence graph in natural language, identifying nodes and edges in the text of a query verifying matches
	between them and corresponding nodes and edges in the evidence graph.

	### A router of questions

	The Formalizer answers a fixed set of questions (see [`Question`][mercury.graph.evidence.Question]), but it does not answer any of
	them itself: every question is answered by the [`Decider`][mercury.graph.evidence.Decider] configured for it. The Formalizer only
	checks the arguments of a question and passes them to its Decider. It has no model, no ontology and no access to any graph: everything
	a question needs (the text, the ontology, the context) is in its arguments, built by the caller (the EvidenceGraph or an Agent).

	The questions are:

	1. `extract_nodes`: every mention of a type of the ontology in a text, with its type and confidence.
	2. `match_node`: whether a mention is a known instance, as a score and a decision ("same").
	3. `extract_edges`: every edge of a relation of the ontology between the nodes of a text.

	`extract_nodes` and `extract_edges` take the 'ontology' (or the part of it to look for), as {'types': [{'id', 'definition'}],
	'relations': [{'id', 'src', 'dst', 'definition'}]}. `match_node` does not: its mention comes with the 'definition' of its type,
	looked up in the ontology by whoever asks. Every question takes, optionally, a 'context'.

	## Configuration

	Every question the Formalizer answers has a key, its name in lowercase, with the name of its Decider in "decider" and its
	configuration in "extra_args":

	```jsonc
	"extract_nodes": {"decider": "gliner_nodes", "extra_args": {"model": "fastino/gliner2.5-base-v1"}},
	"match_node":	 {"decider": "rules", "extra_args": {"same_node_threshold": 0.3}},
	"extract_edges": {"decider": "gliner_edges", "extra_args": {"model": "fastino/gliner2.5-base-v1"}}
	```

	A question without a key (or with null) is not exposed. The Deciders are:

	- `gliner_nodes` ([`GlinerNodesDecider`][mercury.graph.evidence.GlinerNodesDecider]) for `extract_nodes`.
	- `gliner_edges` ([`GlinerEdgesDecider`][mercury.graph.evidence.GlinerEdgesDecider]) for `extract_edges`.
	- `rules` ([`RulesDecider`][mercury.graph.evidence.RulesDecider]) for `match_node`.

	While piloting, the Formalizer creates the Decider of every question configured and calls its `ready()`. If no question is
	configured, a Decider is unknown, answers another question, cannot be created or is not ready, every problem is logged and the
	Formalizer stops in the `ERR_DECIDER_INIT` state.

	## Arguments

	Before passing a question to its Decider, the Formalizer checks that its arguments are those of the question: the required ones are
	there, there is none it does not know, each one has its type (e.g., 'text' is a string) and an object has its required fields (e.g.,
	the 'mention' of `match_node` has "mention", "type" and "definition", and every node of `extract_edges` has "mention" and "id"). If
	any is not, every problem is logged and the question returns None. The content of the ontology is not validated: its coherence is
	checked by whoever loads it (see [`validate_ontology()`](evidence_ontologies.md#validation)).

	## Types and concepts

	A type of the ontology (of entity or of relationship) is called a *concept* in the code (e.g., `_choose_concept()`) and a *type* in
	the arguments and the output of the questions (e.g., the 'types' of the ontology or the 'type' of a node).

	## Known Limitations

	The functionality is still very exploratory and minimalistic. Specifically, the following limitations exist:

	- The extraction threshold is that of GLiNER2 (0.5): it cannot be configured.
	- Every GLiNER2 Decider loads its own model, so the same model can be loaded twice.
	- The only Decider of `match_node` is RulesDecider: it only compares names (it ignores the texts and the descriptions).
	- Pronouns and generic mentions ("she", "the club") are not resolved.
	- The direction of the edges of a relationship with the same type at both ends depends on `extract_relations()`, which finds
	few of them.

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

		self._deciders = {}			# {Question: Decider} of the questions configured, once piloted.

		self._meta_ = self._meta()	# Just to make .meta reflect the initial state.


	def _run(self, request):
		""" Runs the Formalizer with the given request.

			(See [`Agentic.run()`][mercury.graph.evidence.Agentic.run].)
		"""
		question = self.call.get(request['name'], None)

		if question is None:
			self.log_error('Formalizer does not have a function named "%s".' % request['name'])
			raise AgenticRunInvalidRequest

		answer = self._answer(question, request['arguments'])
		ret	   = {'finish_reason': 'stop', 'message': answer}

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
		""" Pilots the Formalizer to a new state based on the given intent: from INITIAL, it creates the Deciders and becomes READY.

		(See [`Agentic.pilot()`][mercury.graph.evidence.Agentic.pilot].)
		"""

		if self.meta['state'] < 0:
			self.log_error('Formalizer is in error state %d' % self._meta_['state'])

			return

		if self._meta_['state'] != self.states.INITIAL.value or intent <= self.states.INITIAL.value:
			return

		deciders = self._load_deciders()

		if deciders is None:
			self._meta_['state'] = self.states.ERR_DECIDER_INIT.value

			return

		self._deciders			= deciders
		self._meta_['state']	= self.states.READY.value


	def extract_nodes(self, arguments):
		""" Answers `extract_nodes`: every mention of a type of the ontology in a text.

		Args:
			arguments (dict): 'text' (str), 'ontology' (dict) and optionally 'context' (list).

		Returns:
			(list): One dictionary per mention with 'mention' (the text as it appears), 'type' and 'confidence', or None if the
				Formalizer cannot answer (see `_answer()`).
		"""

		result = self._answer(Question.EXTRACT_NODES, arguments)

		return result


	def match_node(self, arguments):
		""" Answers `match_node`: whether a mention is a known instance.

		Args:
			arguments (dict): 'mention' ({'mention', 'type', 'definition', 'texts'}), 'node' ({'id', 'description', 'names'}) and
				optionally 'context' (list).

		Returns:
			(dict): 'score' (0..1) and 'same' (bool), or None if the Formalizer cannot answer (see `_answer()`).
		"""

		result = self._answer(Question.MATCH_NODE, arguments)

		return result


	def extract_edges(self, arguments):
		""" Answers `extract_edges`: every edge of a relation of the ontology between the nodes of a text.

		Args:
			arguments (dict): 'text' (str), 'nodes' (list of {'mention', 'id'}), 'ontology' (dict) and optionally 'context' (list).

		Returns:
			(list): One dictionary per edge with 'src', 'relation', 'dst' (ids) and 'confidence', or None if the Formalizer cannot
				answer (see `_answer()`).
		"""

		result = self._answer(Question.EXTRACT_EDGES, arguments)

		return result


	def _answer(self, question, arguments):
		""" Returns the answer of the Decider of a question, or None (logging why) if the Formalizer is not ready, does not answer the
		question or the arguments are not those of the question. """

		if self._meta_['state'] != self.states.READY.value:
			self.log_error('Formalizer %s is not ready for %s.' % (self.id, question.key()))

			return None

		decider = self._deciders.get(question, None)

		if decider is None:
			self.log_error('Formalizer %s does not answer %s.' % (self.id, question.key()))

			return None

		problems = _argument_problems(question, arguments)

		for problem in problems:
			self.log_error('Invalid arguments of %s in Formalizer %s: %s' % (question.key(), self.id, problem))

		if len(problems) > 0:
			return None

		result = decider.run(arguments)

		return result


	def close(self, endpoint_locked):
		""" Closes the Formalizer, persists it to disk and releases any resources it holds.

		(See [`Agentic.close()`][mercury.graph.evidence.Agentic.close].)
		"""

		# There is no state to persist, just freeing resources.
		self._deciders = {}


	def _configured_questions(self):
		""" Returns the questions with a configuration (a key that is not null), in the order of `Question`. """

		questions = []
		for question in Question:
			conf = self.conf.get(question.key(), None)
			if conf is not None:
				questions.append(question)

		return questions


	def _load_deciders(self):
		""" Returns {Question: Decider} of every question configured, or None (logging every problem) if there is none or any Decider
		cannot be loaded. """

		questions = self._configured_questions()

		if len(questions) == 0:
			self.log_error('Formalizer %s answers no question: configure at least one of %s.' % (self.id, _question_keys()))

			return None

		deciders = {}
		failed	 = False
		for question in questions:
			decider = self._load_decider(question)
			if decider is None:
				failed = True
				continue

			deciders[question] = decider

		if failed:
			return None

		return deciders


	def _load_decider(self, question):
		""" Returns the ready Decider of a question, or None (logging why) if its configuration is wrong, it cannot be created or it is
		not ready. """

		decider_class = self._decider_class(question)

		if decider_class is None:
			return None

		conf	   = self.conf[question.key()]
		extra_args = conf.get('extra_args', {})
		decider	   = self._create_decider(question, decider_class, extra_args)

		if decider is None:
			return None

		problems = decider.ready()

		for problem in problems:
			self.log_error('Decider of %s is not ready in Formalizer %s: %s' % (question.key(), self.id, problem))

		if len(problems) > 0:
			return None

		return decider


	def _decider_class(self, question):
		""" Returns the class of the Decider configured for a question, or None (logging why) if the configuration is not a dictionary,
		the Decider is unknown or it answers another question. """

		conf = self.conf[question.key()]

		if type(conf) is not dict:
			self.log_error('The configuration of %s in Formalizer %s must be a dictionary.' % (question.key(), self.id))

			return None

		name		  = conf.get('decider', None)
		decider_class = DECIDERS.get(name, None)

		if decider_class is None:
			self.log_error('Unknown decider "%s" for %s in Formalizer %s.' % (name, question.key(), self.id))

			return None

		if decider_class.QUESTION is not question:
			answered = decider_class.QUESTION.key()
			self.log_error('Decider "%s" answers %s, not %s, in Formalizer %s.' % (name, answered, question.key(), self.id))

			return None

		return decider_class


	def _create_decider(self, question, decider_class, extra_args):
		""" Returns a Decider of decider_class with extra_args, or None (logging why) if creating it fails. """

		try:
			decider = decider_class(extra_args)

		except Exception as e:
			self.log_error('Failed to create the decider of %s in Formalizer %s: %s' % (question.key(), self.id, str(e)))

			return None

		return decider


	def _capabilities(self):
		""" Returns the capabilities of the Formalizer: those of the questions configured, named after the Formalizer (e.g.,
		`extract_nodes_GLiNER2`).

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

		self.call = {}

		capabilities = []
		for question in self._configured_questions():
			capability = question.capability(self.name)
			name	   = capability['function']['name']

			self.call[name] = question
			capabilities.append(capability)

		return capabilities


def _question_keys():
	""" Returns the keys of all the questions, separated by commas (e.g., "extract_nodes, match_node, extract_edges"). """

	keys = []
	for question in Question:
		keys.append(question.key())

	result = ', '.join(keys)

	return result


def _argument_problems(question, arguments):
	""" Returns the problems of the arguments of a question: a required one is missing, one is unknown or one has another type. """

	if type(arguments) is not dict:
		return ['The arguments must be a dictionary.']

	parameters = question.value['function']['parameters']
	properties = parameters['properties']

	problems = []
	for name in parameters['required']:
		if name not in arguments:
			problems.append('Missing argument "%s".' % name)

	for name, value in arguments.items():
		problem = _argument_problem(name, value, properties)
		if problem is not None:
			problems.append(problem)
			continue

		problems += _field_problems(name, value, properties[name])

	return problems


def _argument_problem(name, value, properties):
	""" Returns the problem of one argument (unknown or of another type than its property), or None if it has none. """

	parameter = properties.get(name, None)

	if parameter is None:
		return 'Unknown argument "%s".' % name

	expected = ARGUMENT_TYPES[parameter['type']]

	if not isinstance(value, expected):
		return 'Argument "%s" must be of type %s.' % (name, parameter['type'])

	return None


def _field_problems(name, value, parameter):
	""" Returns the problems of the fields of an argument of the right type: a required field missing from an object, or from an
	object in an array (e.g., the "mention" of the argument 'mention' of `match_node`). """

	if parameter['type'] == 'object':
		required = parameter.get('required', [])
		problems = _missing_fields(name, value, required)

		return problems

	if parameter['type'] == 'array':
		problems = _item_problems(name, value, parameter['items'])

		return problems

	return []


def _item_problems(name, items, item_parameter):
	""" Returns the problems of the items of an array argument whose items have required fields: an item that is not an object or
	that misses one of them. """

	required = item_parameter.get('required', [])

	if len(required) == 0:
		return []

	problems = []
	for position, item in enumerate(items):
		label = '%s[%d]' % (name, position)
		if type(item) is not dict:
			problems.append('Argument "%s" must be an object.' % label)
			continue

		problems += _missing_fields(label, item, required)

	return problems


def _missing_fields(label, value, required):
	""" Returns a problem for every required field missing from an object argument. """

	problems = []
	for field in required:
		if field not in value:
			problems.append('Argument "%s" is missing "%s".' % (label, field))

	return problems
