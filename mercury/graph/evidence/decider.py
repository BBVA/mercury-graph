import re, unicodedata

from abc import ABC, abstractmethod

from .agentic_graph import AgenticGraph
from .question import Question


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

	concept		  = AgenticGraph.parent_of(index)
	other_concept = AgenticGraph.parent_of(other)
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
	""" A Decider answers one of the questions of a [`Formalizer`][mercury.graph.evidence.Formalizer] (see
	[`Question`][mercury.graph.evidence.Question]): the Formalizer validates the arguments and the Decider answers. How it answers
	(with a model, with rules or asking an agent) is up to each implementation.

	A Decider is created by the Formalizer while piloting, with the "extra_args" of its question in the configuration, and the
	Formalizer only uses it if `ready()` finds no problem. A Decider that needs an external library imports it in `ready()`.

	Every Decider answers one question, the `QUESTION` of its class. Its `run()` is given the arguments of that question and returns
	its output, as the question defines them.

	Args:
		extra_args (dict): The configuration of the Decider.
	"""

	QUESTION = None		# The Question the Decider answers.

	def __init__(self, extra_args):
		self.conf = extra_args


	def ready(self):
		""" Checks that the Decider can be used (e.g., that its model is installed and loaded).

		Returns:
			(list): A list of strings, one for each problem found. It is empty if the Decider is ready.
		"""

		return []


	@abstractmethod
	def run(self, arguments):
		""" Answers the question of the Decider.

		Args:
			arguments (dict): The arguments of the question, already validated by the Formalizer.

		Returns:
			The output of the question.
		"""


class RulesDecider(Decider):
	""" A [`Decider`][mercury.graph.evidence.Decider] for `match_node` based on rules, without any model.

	It compares the name of the mention with that of the node: the score is 0 if their types have different roots and the share of
	significant words in common otherwise. The texts, the definitions, the descriptions and the other names are not used. The mention
	is the node ("same") when the score reaches the threshold.

	Its configuration accepts "ignored_words", the words left out of the names (titles by default), and "same_node_threshold" (0.3
	by default, which accepts "Ms. Ruiz" as "Elena Ruiz" with a score of 0.5).
	"""

	QUESTION			= Question.MATCH_NODE
	SAME_NODE_THRESHOLD = 0.3	# Default "same_node_threshold": the score from which a mention is the node.

	def __init__(self, extra_args):
		super().__init__(extra_args)

		self.threshold	   = extra_args.get('same_node_threshold', self.SAME_NODE_THRESHOLD)
		self.ignored_words = extra_args.get('ignored_words', IGNORED_WORDS)


	def run(self, arguments):
		""" Returns the share of significant words in common between the names of the mention and the node, and whether it reaches
		the threshold.

		Args:
			arguments (dict): The arguments of `match_node`: 'mention' ({'mention', 'type', 'texts'}) and 'node' ({'id',
				'description', 'names'}).

		Returns:
			(dict): 'score' (0..1) and 'same' (True when the score reaches the threshold).
		"""

		mention = arguments['mention']
		node	= arguments['node']
		index	= '%s|%s' % (mention['type'], mention['mention'])

		score = compare_names(index, node['id'], self.ignored_words)
		same  = score >= self.threshold

		result = {'score': score, 'same': same}

		return result
