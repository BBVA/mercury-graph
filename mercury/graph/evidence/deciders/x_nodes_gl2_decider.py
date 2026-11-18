from mercury.graph.evidence import AgenticGraph

from .gl2_decider import Gl2Decider


class XNodesGl2Decider(Gl2Decider):
	""" A [`Decider`][mercury.graph.evidence.Decider] that answers `extract_nodes` with GLiNER2 (Basic Entity Extraction).

	## How it answers

	The model is given the types of the ontology in the question, each one named by its id and described by its definition. A mention
	found with several types gets the most specific type compatible with the most confident one (it, its ancestors or its descendants);
	among equally specific types, the most confident is chosen and types of other branches are discarded. The context is not used.

	It knows nothing but the question: the Formalizer gives it the types of the ontology to look for.

	## Configuration

	The `extra_args` of [`Gl2Decider`][mercury.graph.evidence.deciders.Gl2Decider]: "description", "model" (mandatory) and the options
	of the model.

	## Writing another Decider

	This is the example to follow. A Decider:

	1. Calls the constructor of [`Decider`][mercury.graph.evidence.Decider], sets `self.question` to the key of the
	[`Question`][mercury.graph.evidence.Question] it answers and calls `self._meta()` again to publish its capability.
	2. Implements `pilot()`, which loads what it needs (libraries, models) and leaves it in `DeciderState.READY` or in an error state.
	3. Implements `_run()`, which receives `{"name": <its capability>, "arguments": <the arguments of the question>}` and returns
	`{"finish_reason": "stop", "message": <the answer of the question>}`.
	4. Implements `_dry_run()` and, if it holds resources, `close()`.

	Here, the steps 2 to 4 are in [`Gl2Decider`][mercury.graph.evidence.deciders.Gl2Decider], shared with the other GLiNER2 Decider,
	and this class only implements `_answer()`.

	Args:
		schema (str): a schema (a unique name) to use for the Decider's ID.
		extra_args (dict): the configuration for the Decider.
		endpoint (Agentic): an optional Endpoint. It becomes part of the Decider's ID and is available via `self.endpoint`. If not
			provided, the Decider becomes its own Endpoint.
		logger (list): an optional logger to use for logging events. It must provide an `append()` method to add new events.
	"""

	def __init__(self, schema, extra_args, endpoint=None, logger=None):
		super().__init__(schema, extra_args, endpoint=endpoint, logger=logger)

		self.question = 'EXTRACT_NODES'

		self._meta_ = self._meta()	# Must be called again after setting self.question to update the capability.


	def _answer(self, arguments):
		""" Returns one node per mention of a type of the ontology in the text.

		Args:
			arguments (dict): The arguments of `extract_nodes`: 'text' and 'ontology' (its 'types' are used).

		Returns:
			(list): One dictionary per mention with 'mention' (the text as it appears), 'type' and 'confidence' (that of the type).
		"""

		text	   = arguments['text']
		concepts   = arguments['ontology'].get('types', [])
		schema	   = self._create_schema(concepts)
		extraction = self._model.extract(text, schema, include_confidence = True)
		entities   = extraction.get('entities', {})

		concepts_by_mention = self._group_concepts_by_mention(entities)

		result = []
		for mention, candidate_concepts in concepts_by_mention.items():
			node = self._resolve_mention(mention, candidate_concepts)
			result.append(node)

		return result


	def _create_schema(self, concepts):
		""" Returns the schema of the model for the types: {id: definition}. """

		definitions = {}
		for concept in concepts:
			definitions[concept['id']] = concept.get('definition', '')

		schema = self._model.create_schema()
		result = schema.entities(definitions)

		return result


	def _group_concepts_by_mention(self, entities):
		""" Returns {mention: {type: confidence}}, the candidate types of every mention, from the entities found by the model
		({type: [{'text': ..., 'confidence': ...}]}).

		A mention found more than once with the same type keeps its highest confidence.
		"""

		found = {}
		for concept, matches in entities.items():
			for match in matches:
				candidate_concepts = found.setdefault(match['text'], {})
				previous		   = candidate_concepts.get(concept, 0)
				candidate_concepts[concept] = max(match['confidence'], previous)

		return found


	def _resolve_mention(self, mention, candidate_concepts):
		""" Returns the node of a mention: its text, its chosen type and the confidence of that type. """

		concept	   = self._choose_concept(candidate_concepts)
		confidence = candidate_concepts[concept]

		node = {'mention': mention, 'type': concept, 'confidence': confidence}

		return node


	def _choose_concept(self, candidate_concepts):
		""" Returns the most specific candidate type compatible with the most confident one (it, its ancestors or its descendants).

		Among equally specific types, the most confident is chosen (the first one found, if they tie). Types of other branches are
		discarded.
		"""

		anchor = max(candidate_concepts, key = candidate_concepts.get)

		best	  = None
		best_rank = None
		for concept in candidate_concepts:
			if not self._are_compatible(concept, anchor):
				continue

			rank = (concept.count('|'), candidate_concepts[concept])
			if best_rank is None or rank > best_rank:
				best	  = concept
				best_rank = rank

		return best


	def _are_compatible(self, concept, other_concept):
		""" Returns True if one of the types descends from the other (a type descends from itself). """

		descends = AgenticGraph.descends_from(concept, other_concept)
		ascends	 = AgenticGraph.descends_from(other_concept, concept)

		return descends or ascends
