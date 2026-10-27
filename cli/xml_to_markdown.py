import argparse, logging, sys

from mercury.graph.evidence.source_parts.xml_build import DEFAULT_CLUSTER_SIZE, DEFAULT_PAGES_PER_BATCH, build_xml_markdown, default_workers


def main(argv = None):
	""" Converts a MediaWiki XML export into Markdown files before a Source needs them. It runs the same indexer and converter as the
	xml_stream SourceMaker, so the SourceMaker reuses the build instead of converting the export again.

	Args:
		argv (list of str): The command line arguments. None reads sys.argv.

	Returns:
		(int): 0 when the build is ready, 1 otherwise.
	"""

	parser = argparse.ArgumentParser(description = 'Converts a MediaWiki XML export into Markdown files using several processes.')
	parser.add_argument('--src', required = True, help = 'Path to the uncompressed MediaWiki XML export.')
	parser.add_argument('--dst', required = True, help = 'Destination directory of the Markdown files. The index goes to <dst>.xml_build.')
	parser.add_argument('--workers', type = int, default = default_workers(), help = 'Worker processes (default: %(default)s).')
	parser.add_argument('--pages-per-batch', type = int, default = DEFAULT_PAGES_PER_BATCH,
		help = 'Pages per batch when the export is indexed (default: %(default)s).')

	args = parser.parse_args(argv)

	if args.workers < 1 or args.pages_per_batch < 1:
		parser.error('--workers and --pages-per-batch must be at least 1.')

	logging.basicConfig(level = logging.INFO, format = '%(message)s')

	ready = build_xml_markdown(args.src, args.dst, DEFAULT_CLUSTER_SIZE, args.pages_per_batch, args.workers)

	return 0 if ready else 1


if __name__ == '__main__':
	sys.exit(main())
