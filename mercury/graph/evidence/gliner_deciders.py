import os, logging, warnings

from .agentic_graph import AgenticGraph
from .decider import Decider
from .question import Question


MODEL_OPTIONS = ['map_location', 'quantize', 'compile']	# Passed to AutoExtractor.from_pretrained() when they are not None.


class Gliner2Decider(Decider):
	""" The base of the [`Decider`][mercury.graph.evidence.Decider]s that answer with a GLiNER2 model. `ready()` loads the model.

	Its configuration is:

	- "model" (mandatory): the model to load (e.g., "fastino/gliner2.5-base-v1").
	- "map_location", "quantize" and "compile" (optional): passed to `AutoExtractor.from_pretrained()` when they are not null.

	Every GLiNER2 Decider loads its own model.
	"""

	def __init__(self, extra_args):
		super().__init__(extra_args)

		self.model = None


	def ready(self):
		""" Imports GLiNER2 and loads the model.

		(See [`Decider.ready()`][mercury.graph.evidence.Decider.ready].)
		"""

		name = self.conf.get('model', None)
		if name is None:
			return ['"model" is missing in the configuration.']

		extractor = _import_extractor()
		if extractor is None:
			return ['GLiNER2 is not installed (gliner2.AutoExtractor cannot be imported).']

		options = _model_options(self.conf)

		try:
			self.model = _load_model(extractor, name, options)

		except Exception as e:
			problem = 'Failed to load model "%s": %s' % (name, str(e))

			return [problem]

		return []


def _import_extractor():
	""" Returns gliner2.AutoExtractor, or None if it cannot be imported. """

	os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')
	os.environ.setdefault('USE_TF', '0')

	try:
		from gliner2 import AutoExtractor

	except ImportError:
		return None

	return AutoExtractor


def _model_options(conf):
	""" Returns the options of the configuration to pass to `AutoExtractor.from_pretrained()`: those that are not None. """

	options = {}
	for option in MODEL_OPTIONS:
		value = conf.get(option, None)
		if value is not None:
			options[option] = value

	return options


def _load_model(extractor, name, options):
	""" Returns the model loaded with the options, with the logs and warnings of the libraries silenced while loading. """

	previous_disable_level = logging.root.manager.disable
	logging.disable(logging.WARNING)

	try:
		with warnings.catch_warnings():
			warnings.simplefilter('ignore')

			model = extractor.from_pretrained(name, **options)

	finally:
		logging.disable(previous_disable_level)

	return model


class ExtractNodesGliner2Decider(Gliner2Decider):
	""" A [`Decider`][mercury.graph.evidence.Decider] for `extract_nodes` with GLiNER2 (Basic Entity Extraction).

	The model is given the types of the ontology, each one named by its id and described by its definition. A mention found with
	several types gets the most specific type compatible with the most confident one (it, its ancestors or its descendants); among
	equally specific types, the most confident is chosen and types of other branches are discarded. The context is not used.
	"""

	QUESTION = Question.EXTRACT_NODES

	def run(self, arguments):
		""" Returns one node per mention of a type of the ontology in the text.

		Args:
			arguments (dict): The arguments of `extract_nodes`: 'text' and 'ontology' (its 'types' are used).

		Returns:
			(list): One dictionary per mention with 'mention' (the text as it appears), 'type' and 'confidence' (that of the type).
		"""

		text	   = arguments['text']
		concepts   = arguments['ontology'].get('types', [])
		schema	   = self._create_schema(concepts)
		extraction = self.model.extract(text, schema, include_confidence = True)
		entities   = extraction.get('entities', {})

		concepts_by_mention = _group_concepts_by_mention(entities)

		result = []
		for mention, candidate_concepts in concepts_by_mention.items():
			node = _resolve_mention(mention, candidate_concepts)
			result.append(node)

		return result


	def _create_schema(self, concepts):
		""" Returns the schema of the model for the types: {id: definition}. """

		definitions = {}
		for concept in concepts:
			definitions[concept['id']] = concept.get('definition', '')

		schema = self.model.create_schema()
		result = schema.entities(definitions)

		return result


def _group_concepts_by_mention(entities):
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


def _resolve_mention(mention, candidate_concepts):
	""" Returns the node of a mention: its text, its chosen type and the confidence of that type. """

	concept	   = _choose_concept(candidate_concepts)
	confidence = candidate_concepts[concept]

	node = {'mention': mention, 'type': concept, 'confidence': confidence}

	return node


def _choose_concept(candidate_concepts):
	""" Returns the most specific candidate type compatible with the most confident one (it, its ancestors or its descendants).

	Among equally specific types, the most confident is chosen (the first one found, if they tie). Types of other branches are discarded.
	"""

	anchor = max(candidate_concepts, key = candidate_concepts.get)

	best	  = None
	best_rank = None
	for concept in candidate_concepts:
		if not _are_compatible(concept, anchor):
			continue

		rank = (concept.count('|'), candidate_concepts[concept])
		if best_rank is None or rank > best_rank:
			best	  = concept
			best_rank = rank

	return best


def _are_compatible(concept, other_concept):
	""" Returns True if one of the types descends from the other (a type descends from itself). """

	descends = AgenticGraph.descends_from(concept, other_concept)
	ascends	 = AgenticGraph.descends_from(other_concept, concept)

	return descends or ascends


class ExtractEdgesGliner2Decider(Gliner2Decider):
	""" A [`Decider`][mercury.graph.evidence.Decider] for `extract_edges` with GLiNER2 (Structure and Relation Extraction).

	The model is asked for every relation as a structure (`extract_json()`) with a field for each end, named by its type. A relation
	whose ends have the same type (e.g., place to place) has two fields with the same name, so the model only finds that the relation
	is in the text, not its pairs: the model is then asked again, only for those relations, for (head, tail) pairs
	(`extract_relations()`).

	The mentions at both ends are replaced by the ids of the nodes, and the edges are kept if both ends are nodes with an id and their
	types are those of the relation or descendants of them. A repeated edge keeps its highest confidence, and an edge is dropped when
	the same pair has an edge of a more specific relation (e.g., works_on when works_on|leads is found). The context is not used.
	"""

	QUESTION = Question.EXTRACT_EDGES

	def run(self, arguments):
		""" Returns the edges of the relations of the ontology between the nodes of the text.

		Args:
			arguments (dict): The arguments of `extract_edges`: 'text', 'nodes' ({'mention', 'id'}) and 'ontology' (its 'relations'
				are used).

		Returns:
			(list): One dictionary per edge with 'src', 'relation', 'dst' (ids) and 'confidence'.
		"""

		text	  = arguments['text']
		relations = _get_relations(arguments['ontology'])
		ids		  = _ids_by_mention(arguments['nodes'])

		found		 = self._extract_structures(text, relations)
		triples		 = _pair_mentions(found, relations, ids)
		same_concept = _find_same_concept_relations(found, relations)

		if len(same_concept) > 0:
			directed = self._extract_directed_pairs(text, same_concept, relations, ids)
			triples += directed

		result = _finish_edges(triples, relations)

		return result


	def _extract_structures(self, text, relations):
		""" Returns {relation id: matches} found by the model, every relation asked as a structure named by its definition. """

		structures	  = {}
		by_definition = {}
		for index, (src, dst, definition) in relations.items():
			structures[definition]	  = [src, dst]
			by_definition[definition] = index

		extraction = self.model.extract_json(text, structures, include_confidence = True)

		result = {}
		for definition, matches in extraction.items():
			result[by_definition[definition]] = matches

		return result


	def _extract_directed_pairs(self, text, same_concept, relations, ids):
		""" Returns (src id, relation, dst id, confidence) for every (head, tail) pair the model finds for the given relations. """

		schema = {}
		for index in same_concept:
			schema[index] = relations[index][2]

		found = self.model.extract_relations(text, schema, include_confidence = True)
		pairs = found.get('relation_extraction', {})

		triples = []
		for index, matches in pairs.items():
			for pair in matches:
				src	   = ids.get(pair['head']['text'], None)
				dst	   = ids.get(pair['tail']['text'], None)
				triple = (src, index, dst, pair['head']['confidence'])
				triples.append(triple)

		return triples


def _get_relations(ontology):
	""" Returns {id: (src, dst, definition)} of the relations of the ontology. """

	relations = {}
	for relation in ontology.get('relations', []):
		definition = relation.get('definition', '')
		relations[relation['id']] = (relation['src'], relation['dst'], definition)

	return relations


def _ids_by_mention(nodes):
	""" Returns {mention: id} of the nodes. """

	ids = {}
	for node in nodes:
		ids[node['mention']] = node['id']

	return ids


def _pair_mentions(found, relations, ids):
	""" Returns (src id, relation, dst id, confidence) for every pair of mentions of the matches of relations with different end types. """

	triples = []
	for index, matches in found.items():
		src_concept, dst_concept, _ = relations[index]
		if src_concept == dst_concept:
			continue

		for match in matches:
			sources		 = match.get(src_concept, [])
			destinations = match.get(dst_concept, [])
			triples		+= _pair_match(index, sources, destinations, ids)

	return triples


def _pair_match(index, sources, destinations, ids):
	""" Returns a triple for every source and destination mention of one match, with the lowest of both confidences. """

	triples = []
	for src in sources:
		for dst in destinations:
			confidence = min(src['confidence'], dst['confidence'])
			src_id	   = ids.get(src['text'], None)
			dst_id	   = ids.get(dst['text'], None)
			triples.append((src_id, index, dst_id, confidence))

	return triples


def _find_same_concept_relations(found, relations):
	""" Returns the ids of the relations with the same type at both ends that the model found mentions of. """

	result = []
	for index, matches in found.items():
		src_concept, dst_concept, _ = relations[index]
		if src_concept != dst_concept:
			continue

		if _has_mentions(matches):
			result.append(index)

	return result


def _has_mentions(matches):
	""" Returns True if any field of any match has a mention. """

	for match in matches:
		for spans in match.values():
			if len(spans) > 0:
				return True

	return False


def _finish_edges(triples, relations):
	""" Returns the edges of the triples with valid ends, without repeated edges or edges of a relation more generic than another. """

	valid = []
	for triple in triples:
		if _has_valid_ends(triple, relations):
			valid.append(triple)

	best = _keep_highest_confidence(valid)

	result = []
	for (src, index, dst), confidence in best.items():
		if _has_more_specific_edge(src, index, dst, best):
			continue

		edge = {'src': src, 'relation': index, 'dst': dst, 'confidence': confidence}
		result.append(edge)

	return result


def _has_valid_ends(triple, relations):
	""" Returns True if both ends have an id whose type is that of the relation or a descendant of it. """

	src, index, dst, _ = triple
	src_concept, dst_concept, _ = relations[index]

	if src is None or dst is None:
		return False

	src_valid = AgenticGraph.descends_from(AgenticGraph.parent_of(src), src_concept)
	dst_valid = AgenticGraph.descends_from(AgenticGraph.parent_of(dst), dst_concept)

	return src_valid and dst_valid


def _keep_highest_confidence(triples):
	""" Returns {(src, relation, dst): confidence} with the highest confidence of every repeated edge. """

	best = {}
	for src, index, dst, confidence in triples:
		edge	 = (src, index, dst)
		previous = best.get(edge, 0)
		best[edge] = max(confidence, previous)

	return best


def _has_more_specific_edge(src, index, dst, edges):
	""" Returns True if the same pair has an edge of a relation that descends from index. """

	for other_src, other_index, other_dst in edges:
		same_pair = (other_src, other_dst) == (src, dst)
		if same_pair and other_index != index and AgenticGraph.descends_from(other_index, index):
			return True

	return False
