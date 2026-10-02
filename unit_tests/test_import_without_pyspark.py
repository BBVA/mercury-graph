import subprocess
import sys


def test_import_without_pyspark():
    """mercury.graph (and the mge client, through mercury.graph.evidence) can be imported when pyspark is not installed."""

    # Run in a fresh interpreter: in this process mercury.graph may already be imported with pyspark.
    # Setting sys.modules['pyspark'] to None makes any `import pyspark` fail as if it were not installed.
    code = '\n'.join([
        'import sys',
        "sys.modules['pyspark'] = None",
        'import mercury.graph',
        'from mercury.graph.evidence import Endpoint',
        'from mercury.graph.ml import GraphFeatures',
    ])

    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
