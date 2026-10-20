from mercury.graph.evidence import Crawl


def test_101():
	crawl = Crawl(None, None, None)

	assert type(crawl) is Crawl


# if __name__ == "__main__":
# 	pytest.main([__file__])
