import os

from mercury.graph.evidence.formats import PdfToMarkdown


class MDbyPyMuPDF4LLM(PdfToMarkdown):
	""" A custom PdfToMarkdown descendant that uses the PyMuPDF4LLM library to convert a PDF file to Markdown.

	## LICENSE WARNING

	1. PyMuPDF4LLM integration is optional. This project does not include, distribute, or install PyMuPDF4LLM.
	2. PyMuPDF4LLM is not required to use this project.
	3. PyMuPDF4LLM may optionally be used as a PDF conversion backend when separately installed by you.
	4. PyMuPDF4LLM is licensed separately by Artifex Software under the GNU AGPLv3 or a commercial license. Users choosing to
		use the PyMuPDF4LLM backend are responsible for determining whether their use complies with the applicable PyMuPDF4LLM license.
	5. This file is provided for documentation and illustrative purposes only. If you choose to enable, adapt, or use this example with
       PyMuPDF4LLM, you are responsible for ensuring that your resulting use complies with the applicable PyMuPDF4LLM license.

	The conversion uses https://pypi.org/project/pymupdf4llm/
	"""

	def run(self):
		""" Convert the PDF file to Markdown. """

		# md = self.to_markdown(self.src)

		# with open(self.dst, 'w', encoding = 'utf-8') as f:
		# 	f.write(md)

		return True


	def _ready(self):
		""" Check if the converter is ready to run, meaning the dependencies can be imported and the source file exists. """

		# if not os.path.isfile(self.src):
		# 	return False

		# try:
		# 	import pymupdf4llm

		# 	self.to_markdown = pymupdf4llm.to_markdown

		# except ImportError:
		# 	return False

		return True
