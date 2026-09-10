import os

from mercury.graph.evidence.formats import PdfToMarkdown


class MDbyDocling(PdfToMarkdown):
	""" A custom PdfToMarkdown descendant that uses Docling to convert a PDF file to Markdown.

	The conversion uses https://pypi.org/project/docling/

	You have to install docling to make it work since it is not a requirement of mercury-graph.
	"""

	def run(self):
		""" Convert the PDF file to Markdown using the Docling API. """

		md = self.converter.convert(self.src)

		with open(self.dst, 'w', encoding = 'utf-8') as f:
			f.write(md)

		return True


	def _ready(self):
		""" Check if the converter is ready to run, meaning the dependencies can be imported and the source file exists. """

		if not os.path.isfile(self.src):
			return False

		try:
			from docling.document_converter import DocumentConverter, PdfFormatOption
			from docling.datamodel.base_models import InputFormat
			from docling.datamodel.pipeline_options import PdfPipelineOptions

			pipeline_options = PdfPipelineOptions()

			if type(self.extra) is dict:
				pipeline_options.do_ocr = self.extra.get('do_ocr', True)

			self.converter = DocumentConverter(format_options = {InputFormat.PDF: PdfFormatOption(pipeline_options = pipeline_options)})

		except ImportError:
			return False

		return True
