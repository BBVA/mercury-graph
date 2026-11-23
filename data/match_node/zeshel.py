""" Converts ZESHEL (Zero-Shot Entity Linking, Logeswaran et al., 2019) into datasets of match_node, in the format of dataset.py.

ZESHEL links mentions in pages of 16 FANDOM wikis ("worlds") to the pages of the entities they refer to. Its train, val and test
splits have different worlds, so that val and test measure entities and domains never seen in training. It is not included in this
repository (its text is CC BY-SA 3.0): download it from https://github.com/lajanugen/zeshel and give its folder (the one with
"documents" and "mentions") as the first argument.

Run it from the root of the repository:

	python -m data.match_node.zeshel <zeshel folder> [--out FOLDER] [--seed 0]

It writes zeshel_train.jsonl, zeshel_val.jsonl and zeshel_test.jsonl (by default, in zeshel_data/, which is not committed). Every
file starts with a line that describes it (its split, its parameters, the type of the mentions, the breakdowns of its scores and how
many mentions every filter removed) and has a mention per line after it, as in dataset.py:

- the mention is its words in the page where it is found, with a window of --context-words words before and after it (without the
  title that starts the page) as its text. Its type is "entity", since ZESHEL has no types. Only names are used: not mentions without
  letters ("1990"), pronouns, words that work as one ("someone", "here") nor lowercase words ending in "-ed", which are verbs or
  adjectives ("attacked"),
- its candidates are the entity it refers to and other entities of the same world: some whose titles share words with the mention,
  the title of its entity or its text (most of all with the mention), and some random others (--train-candidates and
  --eval-candidates; random ones fill the similar ones that are missing). A candidate whose description is almost the same as that of
  the entity (a duplicated page) is left out,
- the id of a candidate is the title of its page, and its description the first sentences of the page, up to --description-words
  words, without the title that starts every page,
- only entities whose page has at most --max-page-words words are used (as expected entities and as candidates, so that the length
  of a description does not tell the expected one), so that the description keeps most of the page,
- the mentions are sampled with the same number of each category of ZESHEL (HIGH_OVERLAP, MULTIPLE_CATEGORIES, AMBIGUOUS_SUBSTRING,
  LOW_OVERLAP), as far as there are enough, and the candidates are shuffled,
- in val and test, a share --new of the mentions of every category is new: its entity is left out of its candidates, so that the
  right decision is that it is none of them. The other mentions are known, and the same as without --new.

The text of ZESHEL is cleaned: its words and punctuation are joined as usual, as are the plurals of its links ("droid s") and its
numbers ("60, 000", "7. 92"), and the empty references it leaves where it removed a link, such as "()" or '(, "okudagram")', are
removed. Pages that only redirect to Wikipedia, and texts and descriptions that cannot be
cleaned, are left out: those with code of the wikis ("<NormalText ...>", "{{"), lists of links ("Bajor; Borg;;;") or a removed link
that leaves an article or quotes empty ('aboard the, was', 'in the novel " "').

The "meta" of a mention is its status (known or new), its category and its world, and that of a pair its group (see dataset.py): a
positive written as the title of the entity (exact) or not (different), and a negative whose title shares a word with the mention
(homonym) or not (other). The category of ZESHEL compares the mention with the title of its entity: the same (HIGH_OVERLAP), the title
followed by a disambiguation phrase (MULTIPLE_CATEGORIES), a part of the title (AMBIGUOUS_SUBSTRING) or anything else (LOW_OVERLAP).
"""

import argparse, collections, json, os, random, re, sys
from typing import Counter, Dict, List, Optional, Set, Tuple

from data.match_node.dataset import words


SPLITS	   = ('train', 'val', 'test')
OUT		   = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zeshel_data')
REDIRECT   = 'opportunity to redirect'
MIN_WORDS  = 10		# Pages with fewer words after their title are too short to describe an entity.
DUPLICATE  = 0.8	# Share of common words from which two descriptions are of the same entity.
STOPWORDS  = {'a', 'an', 'and', 'as', 'at', 'by', 'de', 'for', 'from', 'in', 'is', 'it', 'its', 'of', 'on', 'or', 'the', 'to',
			  'with'}
TYPE	   = {'id': 'entity', 'definition': 'Anything a page of a wiki describes: a person, a character, a place, an organization, an '
		  'object, a work, an event or a concept.'}
BREAKDOWNS = ['status', 'category', 'group']

PRONOUNS  = {'he', 'she', 'it', 'they', 'him', 'her', 'them', 'his', 'hers', 'its', 'their', 'theirs', 'himself', 'herself',
			 'itself', 'themselves', 'i', 'me', 'my', 'we', 'us', 'our', 'you', 'your', 'this', 'that', 'these', 'those', 'one', 'two',
			 'three', 'another', 'other', 'others', 'someone', 'somebody', 'something', 'everyone', 'everybody', 'everything', 'anyone',
			 'anything', 'here', 'there'}	# Mentions that, like a pronoun, need the text before them to know what they are.
PARTICIPLE = re.compile(r'[a-z]{2,}(?<!e)ed')	# A lowercase word of 4+ letters ending in "-ed", but not "-eed" ("speed").
LETTER	   = re.compile(r'[^\W\d_]')			# A letter, in any alphabet.

JOINS = [													# How detokenize() joins what ZESHEL separates, in order.
	(re.compile(r' ([.,;:!?%)\]])'), r'\1'),					# "ship ." -> "ship."
	(re.compile(r'([(\[]) '), r'\1'),							# "( 1990" -> "(1990"
	(re.compile(r"(\w) ' s\b"), r"\1's"),						# "Luc ' s" -> "Luc's"
	(re.compile(r'(\w) - (?=\w)'), r'\1-'),						# "Jean - Luc" -> "Jean-Luc"
	(re.compile(r'" ([^"]*?) "'), r'"\1"'),						# '" Slave I "' -> '"Slave I"'
	(re.compile(r"(?<!\w)' ([^']{1,80}?) '(?!\w)"), r"'\1'"),	# "' Kingpin '" -> "'Kingpin'"
	(re.compile(r'(?<=\w) s\b'), 's'),							# "droid s" -> "droids": the plural of a link
	(re.compile(r'" s\b'), '"\'s'),								# '"Doctor Who" s' -> '"Doctor Who"\'s'
	(re.compile(r'\s’'), '’'),									# "Kul Tiras ’ s" -> "Kul Tiras’ s"
	(re.compile(r'’ s\b'), '’s'),								# "Kul Tiras’ s" -> "Kul Tiras’s"
	(re.compile(r'(?<=\d), (?=\d{3}\b)'), ','),					# "60, 000" -> "60,000"
	(re.compile(r'(?<![\d.])(\d{1,3})\. (\d{1,3})\b'), r'\1.\2'),	# "7. 92" -> "7.92", but not "515. 2368" (a new sentence)
	(re.compile(r'(?<![\d.])(\d{4,})\. (\d)\b'), r'\1.\2'),			# "stardate 4372. 5" -> "4372.5", but not "2013. 350"
	(re.compile(r'\(\. (?=\d)'), '(.'),							# "(. 312 in)" -> "(.312 in)"
	(re.compile(r'\$ (?=\d)'), '$'),								# "$ 10" -> "$10"
	(re.compile(r'\b([A-Z])\. (?=[A-Z]\.)'), r'\1.'),				# "U. S." -> "U.S."
	(re.compile(r'\.\s(?=(?:com|org|net)\b)'), '.'),				# "Amazon. com" -> "Amazon.com"
	(re.compile(r'\bwww\. '), 'www.')							# "www. lego" -> "www.lego"
]

REFERENCE = re.compile(r'\s*\(\s*(?:[,;][^()]*)?\)')		# "()", "(;)" or '(, "okudagram")'.
PROBLEMS  = {
	'code': re.compile(r'<[^>]{0,80}>|\{\{|\}\}| = "'),
	'list of links': re.compile(r';\s*;|\bReferences\.'),
	'removed link': re.compile(r'\b(?:the|a|an)[,.;:)]|"\s*"', re.IGNORECASE)
}


class World:
	""" The entities of a world that can be candidates, and the index of the words of their titles. """

	def __init__(self, name: str):
		self.name	  = name
		self.entities = {}
		self.ids	  = []
		self.by_word  = {}


	def add(self, document: dict) -> None:
		""" Adds a document as an entity, and the words of its title to the index. """

		self.entities[document['document_id']] = document
		self.ids.append(document['document_id'])
		for word in content_words(document['title']):
			self.by_word.setdefault(word, []).append(document['document_id'])


	def sharing(self, title_words: Set[str]) -> Set[str]:
		""" Returns the ids of the entities whose titles have any of the words. """

		ids = set()
		for word in title_words:
			ids.update(self.by_word.get(word, []))

		return ids


def content_words(text: str) -> Set[str]:
	""" Returns the words of a text, in lower case, without stopwords and single characters. """

	result = set()
	for word in words(text):
		if len(word) > 1 and word not in STOPWORDS:
			result.add(word)

	return result


def detokenize(text: str) -> str:
	""" Returns a text of ZESHEL, whose words and punctuation are separated by spaces, written as usual (e.g., "Jean - Luc ' s droid s ."
	becomes "Jean-Luc's droids.", and "7. 92 mm" becomes "7.92 mm"): see JOINS. """

	for pattern, joined in JOINS:
		text = pattern.sub(joined, text)

	return text


def clean(text: str) -> str:
	""" Returns a text of ZESHEL written as usual and without the empty references where a link was removed. """

	text	 = detokenize(text)
	previous = None
	while text != previous:			# Removing a reference can leave an empty one around it.
		previous = text
		text	 = REFERENCE.sub('', text)

	return ' '.join(text.split())


def problem_of(text: str) -> Optional[str]:
	""" Returns the problem of a cleaned text that cannot be cleaned (see PROBLEMS), or None. """

	for name, pattern in PROBLEMS.items():
		if pattern.search(text):
			return name

	return None


def title_length(document: dict) -> int:
	""" Returns how many words of a page are its title at its start (0 if it does not start with its title). """

	tokens = document['text'].split()
	title  = document['title'].split()
	if tokens[:len(title)] == title:
		return len(title)

	return 0


def description_of(document: dict, description_words: int) -> str:
	""" Returns the description of an entity: the first sentences of its page, without its title, up to description_words words (or
	the first description_words words, if its first sentence is longer). """

	tokens	  = document['text'].split()[title_length(document):]
	text	  = clean(' '.join(tokens))
	sentences = re.split(r'(?<=[.!?]) ', text)

	kept, length = [], 0
	for sentence in sentences:
		length += len(sentence.split())
		if length > description_words:
			break

		kept.append(sentence)

	if len(kept) == 0:
		return ' '.join(text.split()[:description_words])

	return ' '.join(kept)


def page_problem(document: dict, args: argparse.Namespace) -> Optional[str]:
	""" Returns why a page cannot be an entity, before reading its description, or None: it redirects to Wikipedia or its length
	(without its title) is not between MIN_WORDS and --max-page-words words. """

	if REDIRECT in document['text']:
		return 'redirect'

	length = len(document['text'].split()) - title_length(document)
	if length < MIN_WORDS:
		return 'short page'

	if length > args.max_page_words:
		return 'long page'

	return None


def add_description(document: dict, args: argparse.Namespace) -> None:
	""" Sets the description of a page and why it cannot be an entity ("problem", None if it can). Only pages that can be entities
	get a description. """

	document['description'] = None
	document['problem']		= page_problem(document, args)
	if document['problem'] is not None:
		return

	document['description'] = description_of(document, args.description_words)
	document['problem']		= problem_of(document['description'])


def load_documents(root: str, args: argparse.Namespace) -> Dict[str, dict]:
	""" Returns every page of ZESHEL by id, with its world, its description and why it cannot be an entity (None if it can). """

	documents = {}
	for name in sorted(os.listdir(os.path.join(root, 'documents'))):
		world = name[:-len('.json')]
		with open(os.path.join(root, 'documents', name)) as f:
			for line in f:
				document = json.loads(line)
				document['world'] = world
				add_description(document, args)
				documents[document['document_id']] = document

	return documents


def worlds_of(documents: Dict[str, dict]) -> Dict[str, World]:
	""" Returns the worlds, each one with the pages that can be entities. """

	worlds = {}
	for document_id in sorted(documents):
		document = documents[document_id]
		if document['problem'] is not None:
			continue

		world = worlds.setdefault(document['world'], World(document['world']))
		world.add(document)

	return worlds


def load_mentions(root: str, split: str) -> List[dict]:
	""" Returns the mentions of a split of ZESHEL. """

	with open(os.path.join(root, 'mentions', split + '.json')) as f:
		mentions = [json.loads(line) for line in f]

	return mentions


def window_of(document: dict, start: int, end: int, context_words: int) -> str:
	""" Returns the cleaned words of a page around a mention (from start to end, both included), with context_words words on each side,
	without the title at the start of the page (unless the mention is in it). """

	tokens = document['text'].split()
	first  = max(0, start - context_words)
	title  = title_length(document)
	if start >= title:
		first = max(first, title)

	window = tokens[first:end + 1 + context_words]

	return clean(' '.join(window))


def is_name(text: str) -> bool:
	""" Returns False if a mention is not the name of an entity: a mention without letters, such as a year or a number ("1990", "481"),
	a pronoun or a word that works as one ("one", "someone", "here"), or a lowercase word ending in "-ed", which is a verb or an
	adjective ("attacked", "unnamed"). """

	if LETTER.search(text) is None:
		return False

	if text.lower() in PRONOUNS:
		return False

	return PARTICIPLE.fullmatch(text) is None


def mention_problem(mention: dict, documents: Dict[str, dict], args: argparse.Namespace) -> Optional[str]:
	""" Returns why a mention cannot be used, or None: it is not a name, its entity cannot be one, its page is missing or redirects, or
	its text has a problem. Sets its cleaned text ("window") if it can be used. """

	if not is_name(mention['text']):
		return 'mention: not a name'

	entity	= documents.get(mention['label_document_id'])
	context = documents.get(mention['context_document_id'])
	if entity is None or context is None:
		return 'missing page'

	if entity['problem'] is not None:
		return 'entity: ' + entity['problem']

	if REDIRECT in context['text']:
		return 'text: redirect'

	window = window_of(context, mention['start_index'], mention['end_index'], args.context_words)
	text_problem = problem_of(window)
	if text_problem is not None:
		return 'text: ' + text_problem

	mention['window'] = window

	return None


def eligible_of(mentions: List[dict], documents: Dict[str, dict], args: argparse.Namespace) -> Tuple[List[dict], Counter]:
	""" Returns the mentions that can be used, and how many of the others cannot be used for every reason. """

	eligible = []
	removed	 = collections.Counter()
	for mention in mentions:
		problem = mention_problem(mention, documents, args)
		if problem is None:
			eligible.append(mention)
		else:
			removed[problem] += 1

	return eligible, removed


def sample(mentions: List[dict], size: int, rng: random.Random) -> List[dict]:
	""" Returns a sample of the mentions with the same number of each category, as far as there are enough: the rest is filled with
	other mentions of the categories that have more. """

	by_category = {}
	for mention in sorted(mentions, key = lambda m: m['mention_id']):
		by_category.setdefault(mention['category'], []).append(mention)

	chosen = []
	rest   = []
	share  = size//len(by_category)
	for category in sorted(by_category):
		pool = by_category[category]
		rng.shuffle(pool)
		chosen += pool[:share]
		rest   += pool[share:]

	rng.shuffle(rest)
	chosen += rest[:size - len(chosen)]

	return chosen


def new_ids(mentions: List[dict], share: float, rng: random.Random) -> Set[str]:
	""" Returns the ids of the mentions that are new: a share of those of every category. """

	by_category = {}
	for mention in sorted(mentions, key = lambda m: m['mention_id']):
		by_category.setdefault(mention['category'], []).append(mention['mention_id'])

	ids = set()
	for category in sorted(by_category):
		pool  = by_category[category]
		count = round(share*len(pool))
		ids.update(rng.sample(pool, count))

	return ids


def is_duplicate(document: dict, gold: dict) -> bool:
	""" Returns True if the description of a page is almost the same as that of the entity: they share DUPLICATE of their words. """

	first	= content_words(document['description'])
	second	= content_words(gold['description'])
	union	= first | second
	if len(union) == 0:
		return True

	return len(first & second)/len(union) >= DUPLICATE


def similar_ids(mention_words: Set[str], gold: dict, window: str, world: World, rng: random.Random) -> List[str]:
	""" Returns the ids of the entities of a world whose titles share words with the mention, the title of its entity or its text, the
	most similar first: a shared word counts 3 if it is in the mention, 2 if it is in the title of its entity and 1 if it is in its
	text. Ties are in random order. """

	gold_words	 = content_words(gold['title'])
	window_words = content_words(window)
	ids			 = world.sharing(mention_words | gold_words | window_words)
	ids.discard(gold['document_id'])

	ordered = sorted(ids)
	rng.shuffle(ordered)

	scores = {}
	for entity_id in ordered:
		title = content_words(world.entities[entity_id]['title'])
		scores[entity_id] = 3*len(title & mention_words) + 2*len(title & gold_words) + len(title & window_words)

	return sorted(ordered, key = lambda entity_id: -scores[entity_id])


def random_ids(world: World, excluded: Set[str], count: int, rng: random.Random) -> List[str]:
	""" Returns the ids of random entities of a world that are not excluded, in random order: at least count of them, and more to
	leave out duplicates, if the world has enough. """

	size = min(len(world.ids), 2*count + len(excluded))

	ids = []
	for entity_id in rng.sample(world.ids, size):
		if entity_id not in excluded:
			ids.append(entity_id)

	return ids


def pick(ids: List[str], world: World, gold: dict, count: int) -> List[str]:
	""" Returns the first count ids whose pages are not duplicates of the entity. """

	picked = []
	for entity_id in ids:
		if len(picked) == count:
			break

		if not is_duplicate(world.entities[entity_id], gold):
			picked.append(entity_id)

	return picked


def group_of(mention: str, title: str, gold: bool) -> str:
	""" Returns the group of a pair: a positive written as the title of its entity or not, or a negative whose title shares a word with
	the mention or not. """

	if gold:
		return 'positive exact' if mention.lower() == title.lower() else 'positive different'

	common = words(mention) & words(title)

	return 'negative homonym' if len(common) > 0 else 'negative other'


def candidate_of(document: dict, mention: str, gold: bool) -> dict:
	""" Returns an entity as a candidate of a mention. """

	title = detokenize(document['title'])
	node  = {'id': title, 'description': document['description']}
	meta  = {'group': group_of(mention, title, gold)}

	return {'node': node, 'gold': gold, 'meta': meta}


def convert(mention: dict, documents: Dict[str, dict], world: World, counts: List[int], new: bool, rng: random.Random) -> dict:
	""" Returns a mention of ZESHEL in the format of dataset.py, with its entity and counts[0] similar and counts[1] random candidates
	(more random ones if there are not enough similar ones). A new mention is the same without its entity. """

	gold = documents[mention['label_document_id']]
	text = detokenize(mention['text'])

	similar	 = pick(similar_ids(content_words(text), gold, mention['window'], world, rng), world, gold, counts[0])
	excluded = set(similar) | {gold['document_id']}
	missing	 = counts[0] - len(similar)
	others	 = pick(random_ids(world, excluded, counts[1] + missing, rng), world, gold, counts[1] + missing)

	candidates = [candidate_of(gold, text, True)]
	for entity_id in similar + others:
		candidates.append(candidate_of(world.entities[entity_id], text, False))

	rng.shuffle(candidates)
	if new:
		candidates = without_gold(candidates)

	status = 'new' if new else 'known'
	found  = {'mention': text, 'type': TYPE['id'], 'texts': [mention['window']]}
	meta   = {'status': status, 'category': mention['category'], 'world': mention['corpus']}

	return {'mention_id': mention['mention_id'], 'meta': meta, 'mention': found, 'candidates': candidates}


def without_gold(candidates: List[dict]) -> List[dict]:
	""" Returns the candidates without the expected one. """

	result = []
	for candidate in candidates:
		if not candidate['gold']:
			result.append(candidate)

	return result


def header_of(split: str, args: argparse.Namespace, counts: List[int], share: float, removed: Counter, eligible: int,
			  mentions: List[dict]) -> dict:
	""" Returns the first line of the file of a split: what it is, how it was made and how many mentions every filter removed. """

	params = {'context_words': args.context_words, 'description_words': args.description_words, 'max_page_words': args.max_page_words,
			  'similar': counts[0], 'random': counts[1], 'new': share, 'seed': args.seed}
	info   = {'name': 'zeshel_' + split, 'source': 'ZESHEL', 'split': split, 'types': [TYPE], 'breakdowns': BREAKDOWNS,
			  'params': params, 'removed_mentions': dict(removed.most_common()), 'eligible_mentions': eligible,
			  'mentions': len(mentions)}

	return {'dataset': info}


def write(path: str, header: dict, mentions: List[dict]) -> None:
	""" Writes a dataset: its header in the first line and a mention per line. """

	os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok = True)
	with open(path, 'w') as f:
		f.write(json.dumps(header) + '\n')
		for mention in mentions:
			f.write(json.dumps(mention) + '\n')


def convert_split(split: str, root: str, documents: Dict[str, dict], worlds: Dict[str, World], args: argparse.Namespace) -> str:
	""" Converts a sample of a split and writes it. Returns the path of the file. """

	rng	   = random.Random('%s-%s' % (args.seed, split))
	size   = getattr(args, split)
	counts = args.train_candidates if split == 'train' else args.eval_candidates
	share  = 0.0 if split == 'train' else args.new

	eligible, removed = eligible_of(load_mentions(root, split), documents, args)
	chosen			  = sample(eligible, size, rng)
	new_rng			  = random.Random('%s-%s-new' % (args.seed, split))
	new				  = new_ids(chosen, share, new_rng)

	mentions = []
	for mention in chosen:
		world	= worlds[mention['corpus']]
		is_new	= mention['mention_id'] in new
		mentions.append(convert(mention, documents, world, counts, is_new, rng))

	path   = os.path.join(args.out, 'zeshel_%s.jsonl' % split)
	header = header_of(split, args, counts, share, removed, len(eligible), mentions)
	write(path, header, mentions)

	print('%-5s %5d mentions of %d eligible -> %s' % (split, len(mentions), len(eligible), path))

	return path


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description = 'Converts ZESHEL into datasets of match_node.')
	parser.add_argument('zeshel', help = 'the folder of ZESHEL, with "documents" and "mentions"')
	parser.add_argument('--out', default = OUT, help = 'the folder of the datasets (by default, zeshel_data/)')
	parser.add_argument('--train', type = int, default = 2000, help = 'mentions of train')
	parser.add_argument('--val', type = int, default = 500, help = 'mentions of val')
	parser.add_argument('--test', type = int, default = 500, help = 'mentions of test')
	parser.add_argument('--context-words', type = int, default = 50, help = 'words of the text before and after the mention')
	parser.add_argument('--description-words', type = int, default = 100, help = 'maximum words of a description')
	parser.add_argument('--max-page-words', type = int, default = 200, help = 'maximum words of the page of an entity')
	parser.add_argument('--train-candidates', type = int, nargs = 2, default = [4, 3], metavar = ('SIMILAR', 'RANDOM'),
						help = 'similar and random candidates of a mention of train')
	parser.add_argument('--eval-candidates', type = int, nargs = 2, default = [10, 5], metavar = ('SIMILAR', 'RANDOM'),
						help = 'similar and random candidates of a mention of val and test')
	parser.add_argument('--new', type = float, default = 0.2, help = 'share of the mentions of val and test that are new')
	parser.add_argument('--seed', type = int, default = 0, help = 'the seed of the samples')

	return parser.parse_args(argv)


def main() -> int:
	args	  = parse_args()
	documents = load_documents(args.zeshel, args)
	worlds	  = worlds_of(documents)

	for split in SPLITS:
		convert_split(split, args.zeshel, documents, worlds, args)

	return 0


if __name__ == '__main__':
	sys.exit(main())
