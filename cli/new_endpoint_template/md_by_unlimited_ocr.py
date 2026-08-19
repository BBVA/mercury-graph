import os

from mercury.graph.evidence.formats import PdfToMarkdown


class MDbyUnlimitedOCR(PdfToMarkdown):
	""" This class is experimental. It uses baidu/Unlimited-OCR running as a server in a local docker with access to your GPU.

	It accepts a stream of images as input and its own text format which includes bounding boxes and text. The model is multi-page
	and does everything in one pass, images, layout, and text. It is fast and accurate, therefore it is a good candidate for
	experimentation, but this class is far from being production-ready.

	## Baidu Unlimited-OCR

	  * https://github.com/baidu/Unlimited-OCR
	  * https://arxiv.org/abs/2606.23050

	## PREREQUISITES

	(Linux only)

	### Make apt aware of the NVIDIA repositories to find nvidia-container-toolkit

	```bash
	sudo apt-get update && sudo apt-get install -y --no-install-recommends \
	ca-certificates \
	curl \
	gnupg2

	curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
	&& curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
		sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
		sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

	sudo apt-get update
	```

	### Install toolkit and make it run in docker

	```bash
	sudo apt install nvidia-container-toolkit
	sudo nvidia-ctk runtime configure --runtime=docker
	sudo systemctl restart docker
	```

	### Download the docker image

	```bash
	docker pull vllm/vllm-openai:unlimited-ocr
	```

	### Start the docker container with GPU access as the server on the same machine as Mercury Graph

	```bash
	docker run --rm --gpus all --network host --ipc host \
	vllm/vllm-openai:unlimited-ocr \
	baidu/Unlimited-OCR \
	--trust-remote-code \
	--gpu-memory-utilization 0.90 \
	--max-model-len 16384 \
	--logits_processors vllm.model_executor.models.unlimited_ocr:NGramPerReqLogitsProcessor \
	--no-enable-prefix-caching \
	--mm-processor-cache-gb 0
	```

	Note: You can try to tweak --gpu-memory-utilization 0.90 and --max-model-len 16384 for your own GPU's available memory.

	"""

	def run(self):
		""" Convert the PDF file to Markdown using the Baidu Unlimited-OCR API. """

		import fitz  	# pip install pymupdf
		import base64
		from openai import OpenAI

		def pdf_to_images(pdf_path, dpi = 300):
			doc	   = fitz.open(pdf_path)
			images = []

			mat = fitz.Matrix(dpi/72, dpi/72)

			for page in doc:
				pix = page.get_pixmap(matrix = mat)
				images.append(pix.tobytes('png'))

			doc.close()

			return images

		def image_as_base64(image_bytes):
			b64 = base64.b64encode(image_bytes).decode()

			return {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,%s' % b64}}

		content = [{'type': 'text', 'text': '<image>Multi page parsing.'}]

		for img in pdf_to_images(self.src):
			content.append(image_as_base64(img))

		messages = [{'role': 'user', 'content': content}]

		client = OpenAI(api_key = 'EMPTY', base_url = 'http://localhost:8000/v1', timeout = 3600)

		response = client.chat.completions.create(
			model		= 'baidu/Unlimited-OCR',
			messages	= messages,
			temperature	= 0.0,
			max_tokens	= 16000,
			extra_body	= {'skip_special_tokens': False, 'vllm_xargs': {'ngram_size': 35, 'window_size': 128}}
		)

		md = response.choices[0].message.content

		# NOTE: This is not a markdown file, it is a custom text format that includes bounding boxes and text.
		# A real implementation should parse this into a proper markdown file.

		with open(self.dst, 'w', encoding = 'utf-8') as f:
			f.write(md)

		return True


	def _ready(self):
		""" Check if the converter is ready to run, meaning the dependencies can be imported and the source file exists. """

		if not os.path.isfile(self.src):
			return False

		try:
			import fitz  	# pip install pymupdf
			import base64
			from openai import OpenAI, APIConnectionError, APITimeoutError

		except ImportError:
			return False

		client = OpenAI(api_key = 'EMPTY', base_url = 'http://localhost:8000/v1', timeout = 5)

		try:
			client.models.list()

		except (APIConnectionError, APITimeoutError):
			return False

		return True
