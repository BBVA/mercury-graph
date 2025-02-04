import os, shutil


# Move tutorials inside mercury.graph before packaging
if os.path.exists('tutorials'):
    shutil.move('tutorials', 'mercury/graph/tutorials')


from setuptools import setup, find_packages


setup_args = dict(
	name				 = 'mercury-graph',
	packages			 = find_packages(include = ['mercury*', 'tutorials*'], exclude = ['docker', 'unit_tests']),
	scripts				 = ['test.sh'],
	include_package_data = True,
	package_data		 = {'mypackage': ['tutorials/*', 'tutorials/data/*']}
)

setup(**setup_args)
