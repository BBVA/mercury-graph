from mercury.graph.evidence import Source


def test_source(tmp_path):
	""" Exercise Source initialization, piloting, and capability calls. """
	(tmp_path / 'source.md').write_text('# Source\n')
	conf = {'type': 'markdown_tree', 'src_path': None, 'dst_path': str(tmp_path)}
	s = Source(schema = 'any', extra_args = conf)
	assert type(s) is Source
	assert Source(schema = 'any', extra_args = conf).conf == conf
	assert s.state_name(0) == 'INITIAL'

	s.pilot(100)
	request = {'name': 'children_by_idx_any', 'arguments': {'index': 'any'}}
	assert s.run(request)['message'] == ['any|source.md']
	assert s._dry_run(request) == {'status': 0, 'description': 'Valid request.'}
	assert type(s.meta) == dict

	s._meta_['state'] = -1
	s.pilot(100)


# if __name__ == "__main__":
# 	pytest.main([__file__])
