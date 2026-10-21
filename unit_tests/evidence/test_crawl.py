import pytest

from mercury.graph.evidence import Crawl


def test_101():
	with pytest.raises(TypeError):
		crawl = Crawl(None, None)

	crawl = Crawl({'root_id': ''}, {})

	assert type(crawl) is Crawl
	assert crawl.finished is False
	assert crawl.nodes_done == 0
	assert crawl.nodes_pending == 1
	assert crawl.error is False

	assert crawl.run() is True


# if __name__ == "__main__":
# 	pytest.main([__file__])
