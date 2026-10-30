import re, unicodedata

from abc import ABC, abstractmethod

from .agentic_graph import parent_of


IGNORED_WORDS = ['mr', 'mrs', 'ms', 'miss', 'dr', 'prof']	# Default "ignored_words": titles left out when comparing names.


def compare_names(index, other, ignored_words):
	""" Returns the share of significant words in common between the names of two ids, or 0 if their types have different roots.

	The words of the types of both ids, possessives, accents and the ignored words are left out.

	Args:
		index (str): An id, a type followed by a name (e.g., `person|teacher|Ms. Ruiz`).
		other (str): The other id.
		ignored_words (list): The words left out of both names (e.g., titles).

	Returns:
		(float): A score in [0..1], 1.0 when all the significant words are in common.
	"""

	concept		  = parent_of(index)
	other_concept = parent_of(other)
	if not _have_same_root(concept, other_concept):
		return 0

	ignored		= set(ignored_words)
	generic		= _get_words(concept) | _get_words(other_concept)
	words		= _get_significant_words(index.rsplit('|', 1)[1], generic, ignored)
	other_words = _get_significant_words(other.rsplit('|', 1)[1], generic, ignored)

	result = _jaccard(words, other_words)

	return result


def _have_same_root(concept, other_concept):
	""" Returns True if both types are under the same root type (person|teacher and person|student are). """

	if concept is None or other_concept is None:
		return False

	return concept.split('|')[0] == other_concept.split('|')[0]


def _get_significant_words(name, generic, ignored):
	""" Returns the words of a name without possessives, the generic words (those of the types) and the ignored words. """

	without_possessives = re.sub("['’]s\\b", '', name)

	result = _get_words(without_possessives) - generic - ignored

	return result


def _get_words(text):
	""" Returns the set of lowercase words of a text, without accents (`|` and `_` separate words). """

	decomposed = unicodedata.normalize('NFKD', text.lower())
	plain	   = ''.join(char for char in decomposed if not unicodedata.combining(char))

	result = set(re.findall('[^\\W_]+', plain))

	return result


def _jaccard(words, other_words):
	""" Returns the share of words in common between two sets of words (0 if both are empty). """

	every = words | other_words

	if len(every) == 0:
		return 0

	result = len(words & other_words)/len(every)

	return result


class Decider(ABC):
	""" A Decider answers the questions of a [`Formalizer`][mercury.graph.evidence.Formalizer] about the nodes it finds: whether a
	mention is a known instance and which one of several candidates it is.

	The Formalizer gathers the context (the mention, its type, the definitions of the ontology and the texts) and the Decider only
	decides: how it asks its model (or applies its rules) is up to each implementation.

	The arguments are:

	- A mention: a dictionary with 'mention' (the text as it appears), 'type' (its type in the ontology), 'type_definition'
	(the definition of its type in the ontology) and 'texts' (a list of the texts where it was found). A mention has no id: ids are
	given by the EvidenceGraph.
	- A node (a known instance): a dictionary with 'id' (its type followed by its name, e.g., `person|teacher|Elena Ruiz`) and
	'type_definition' (the definition of its type in the ontology).

	A Decider is created by the Formalizer while piloting, with the "decider" section of its configuration (without "type"), and the
	Formalizer only uses it if `ready()` finds no problem. A Decider that needs an external library imports it in `ready()`.

	The scores of `is_same_node()` mean different things for each Decider, so each one has its own threshold: the score from which
	a candidate is accepted as the instance of a mention. It is "same_node_threshold" in the configuration and, without it, the
	`SAME_NODE_THRESHOLD` of the class.

	Args:
		conf (dict): The configuration of the Decider.
	"""

	SAME_NODE_THRESHOLD = 0.5	# Default "same_node_threshold": the is_same_node() score from which a candidate is accepted.

	def __init__(self, conf):
		self.conf	   = conf
		self.threshold = conf.get('same_node_threshold', self.SAME_NODE_THRESHOLD)


	def ready(self):
		""" Checks that the Decider can be used (e.g., that its model is installed and loaded).

		Returns:
			(list): A list of strings, one for each problem found. It is empty if the Decider is ready.
		"""

		return []


	@abstractmethod
	def is_same_node(self, mention, node):
		""" Scores how likely a mention is a known instance.

		Args:
			mention (dict): The mention (see the class).
			node (dict): The known instance (see the class).

		Returns:
			(float): A score in [0..1].
		"""


	@abstractmethod
	def choose_node(self, mention, nodes):
		""" Chooses which of several known instances a mention is.

		Args:
			mention (dict): The mention (see the class).
			nodes (list): The candidate known instances (see the class).

		Returns:
			(str): The id of the chosen node, or None if none of them can be chosen.
		"""


class RulesDecider(Decider):
	""" A [`Decider`][mercury.graph.evidence.Decider] based on rules, without any model.

	- `is_same_node()` compares the name of the mention with that of the node, as `hint_nodes` does with its candidates: 0 if their
	types have different roots and the share of significant words in common otherwise. The texts and the definitions are not used.
	- `choose_node()` never chooses: it returns None.

	Its configuration accepts "ignored_words", the words left out of the names (titles by default), and "same_node_threshold" (0.3
	by default, which accepts "Ms. Ruiz" as "Elena Ruiz" with a score of 0.5).
	"""

	SAME_NODE_THRESHOLD = 0.3

	def is_same_node(self, mention, node):
		""" Returns the share of significant words in common between the names of the mention and the node.

		(See [`Decider.is_same_node()`][mercury.graph.evidence.Decider.is_same_node].)
		"""

		index	= '%s|%s' % (mention['type'], mention['mention'])
		ignored = self.conf.get('ignored_words', IGNORED_WORDS)

		result = compare_names(index, node['id'], ignored)

		return result


	def choose_node(self, mention, nodes):
		""" Returns None: rules cannot choose between candidates.

		(See [`Decider.choose_node()`][mercury.graph.evidence.Decider.choose_node].)
		"""

		return None


DECIDERS = {'rules': RulesDecider}	# The Decider of every "type" in the "decider" section of the configuration of a Formalizer.
