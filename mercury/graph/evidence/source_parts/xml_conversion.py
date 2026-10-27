import re, unicodedata
from io import BytesIO

from lxml import etree

from mercury.graph.evidence.formats import WikiMarkdownWriter


MEDIAWIKI_NS = 'http://www.mediawiki.org/xml/export-0.11/'

PAGE_TAG = '{%s}page' % MEDIAWIKI_NS
NS = {'mw': MEDIAWIKI_NS}

# ':' is encoded too, so cluster keys such as '1:1' can never match a file name.
REX_KWAP = re.compile('(^ |[<>:"/\\\\|?*\\x00-\\x1f])')	# Characters that cannot appear in file names, and leading spaces.


def page_file_name(title):
	""" Returns the file name of the Markdown file of a page. The characters that cannot appear in file names are %-encoded, and so
	are leading spaces. Trailing spaces are removed.

	Args:
		title (str): The title of the page.

	Returns:
		(str): The file name, without a directory, ending in '.md'.
	"""

	return '%s.md' % REX_KWAP.sub(lambda m: '%%%02X' % ord(m.group()), title).rstrip(' ')


def collision_key(name):
	""" Returns the key that identifies the file names that would clash on case-insensitive or Unicode-normalizing file systems.

	Args:
		name (str): A file name, as returned by page_file_name().

	Returns:
		(str): The normalized and case-folded file name.
	"""

	return unicodedata.normalize('NFD', name).casefold()


def write_page_as_md(dst, title, elem):
	""" Writes a Wikipedia XML page as a Markdown file.

	The XML export keeps the article contents as MediaWiki wikitext in the ``revision/text`` element. This function extracts that text,
	renders the common document structures to Markdown, and adds the article title as the level-one heading.

	Args:
		dst (str): The destination directory. It must exist.
		title (str): Article title from the XML page element.
		elem (lxml.etree._Element): Completed MediaWiki ``page`` element.

	Returns:
		(str): Path of the written Markdown file.
	"""

	fn = '%s/%s' % (dst, page_file_name(title))

	page_text = ''
	for child in elem.iter():
		if type(child.tag) is str and etree.QName(child).localname == 'text':
			page_text = child.text or ''
			break

	body = WikiMarkdownWriter(page_text).render()

	with open(fn, 'w', encoding = 'utf-8') as f:
		f.write('# %s\n\n' % title)
		f.write(body)

	return fn


def convert_batch(src, dst, root, batch):
	""" Converts the pages of one batch of a MediaWiki XML export into Markdown files. This is the unit of work of the worker processes,
	so it needs neither a SourceMaker nor the index.

	The source is opened read-only and only the byte range of the batch is read. The range is wrapped with the root element, so lxml
	can parse its pages. Each page is written and cleared as soon as it is converted.

	Args:
		src (str): Path to the uncompressed MediaWiki XML export.
		dst (str): The destination directory of the Markdown files. It must exist.
		root (str): The opening tag of the MediaWiki root element, with its namespace declarations.
		batch (dict): The batch from the manifest: its 'id', its 'start' and 'end' byte offsets, and the expected 'pages' count.

	Returns:
		(int): The number of pages converted. It raises ValueError when that differs from the expected count.
	"""

	size = batch['end'] - batch['start']

	with open(src, 'rb') as f:
		f.seek(batch['start'])
		body = f.read(size)

	if len(body) != size:
		raise ValueError('Batch %d is outside of the XML file.' % batch['id'])

	payload = BytesIO(root.encode('utf-8') + body + b'</mediawiki>')

	converted = 0
	for event, elem in etree.iterparse(payload, events = ('end',), tag = PAGE_TAG):
		title = elem.findtext('mw:title', namespaces = NS)

		write_page_as_md(dst, title, elem)
		converted += 1

		elem.clear()	# Clear the element to free memory.

		while elem.getprevious() is not None:	# Also clear the previous siblings of the element to free memory.
			del elem.getparent()[0]

	if converted != batch['pages']:
		raise ValueError('Batch %d converted %d pages, expected %d.' % (batch['id'], converted, batch['pages']))

	return converted
