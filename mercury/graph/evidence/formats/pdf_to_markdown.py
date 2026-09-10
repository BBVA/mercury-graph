import os

from abc import ABC, abstractmethod


class PdfToMarkdown(ABC):
	""" The abstract base class for converting a PDF file to Markdown.

	To support every possible technology, (oss, proprietary, cloud, etc.) this is built around custom descendants of this class.

	There are multiple classes supporting different technologies already implemented. Build a new Endpoint using the `mge` client to
	see the different implementations: MDbyDocling, MDbyPyMuPDF4LLM, MDbyUnlimitedOCR, ...

	The simple baseline is MDbyPdfOxide and is part of the mercury-graph library (the rest are just tutorials). It is built around
	[pdf-oxide](https://pypi.org/project/pdf-oxide/). To use it, you need to install pdf-oxide since it is not a requirement.

	Run `pip install pdf-oxide` to install it.

	This baseline is extremely fast and good with text-based PDFs, but other converters may cover a wider range of PDFs and capture
	more details especially with graphic content.

	## To make the Source use custom PdfToMarkdown descendants

	1. Write a new class just like in the .py examples you will find when creating a new Endpoint with the `mge` client.
	2. Include it in the configuration of your Source in a similar way as this
	```json
	"pdf_to_markdown": {
		"class_name": "MDbyDocling",
		"$path": "md_by_docling.py",
		"extra_args": {"do_ocr": false}
	},
	```

	## Using converters

	The usage is done in three steps:

	1. Constructing the PdfToMarkdown descendant object. This just stores the paths and extra arguments.
	2. Verifying that the converter is ready by reading the `ready` property. There will be no conversion if this is False. This
		checks, files, dependencies, and server availability, whatever is needed for running the converter.
	3. Calling the `run()` method to perform the conversion. This actually writes the output file.

	## Using other document formats than PDF as the source

	The SourceMaker type `'pdf_mirror'` can actually work with whatever document format you wish since it does not read the file.
	It just maps the file to a corresponding Markdown file. The PdfToMarkdown descendant does the conversion and since it is a custom
	class, there is no restriction on the source file format. We just use the word "PDF" out of habit since it is the lingua franca of
	document formats. Some of the libraries we give as examples already include support for Word, Excel, PowerPoint, and HWP/HWPX
	(E.g., pymupdfpro instead pymupdf4llm from https://github.com/pymupdf/pymupdf4llm) Only the destination file is format is important,
	which is Markdown.

	Args:
		src (str): The path to the source PDF file.
		dst (str): The path to the destination Markdown file.
		extra_args (dict, optional): Any extra arguments needed for the conversion. Defaults to None.
	"""

	def __init__(self, src, dst, extra_args = None):
		self.src   = os.path.abspath(src)
		self.dst   = os.path.abspath(dst)
		self.extra = extra_args


	@property
	def ready(self):
		""" Check if the converter is ready to run. """
		return self._ready()


	@abstractmethod
	def run(self):
		""" Convert the PDF file to Markdown.

		This is the actual file conversion method. It reads self.src and writes to self.dst. It may use self.extra for any extra arguments.

		Returns:
			(bool): True if the conversion was successful, False otherwise.
		"""

		pass


	@abstractmethod
	def _ready(self):
		""" Check if the converter is ready to run, meaning: the dependencies can be imported, the server (if required) is running, and
		the source file exists.

		Returns:
			(bool): True if the converter is ready to run, False otherwise.
		"""

		pass


class MDbyPDFoxide(PdfToMarkdown):
	""" A custom PdfToMarkdown descendant that uses the pdf-oxide library to convert a PDF file to Markdown.

	The conversion uses https://pypi.org/project/pdf-oxide/

	You have to install pdf-oxide to make it work since it is not a requirement of mercury-graph.
	"""

	def run(self):
		""" Convert the PDF file to Markdown. """

		from pdf_oxide import PdfDocument

		doc	= PdfDocument(self.src)
		md	= doc.to_markdown_all(detect_headings = True)

		with open(self.dst, 'w', encoding = 'utf-8') as f:
			f.write(md)

		return True


	def _ready(self):
		""" Check if the converter is ready to run, meaning the dependencies can be imported and the source file exists. """

		if not os.path.isfile(self.src):
			return False

		try:
			from pdf_oxide import PdfDocument

		except ImportError:
			return False

		return True
