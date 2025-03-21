import os
import pytest
import warnings
from mercury.graph.core import Graph
from mercury.graph.core.spark_interface import pyspark_installed
from mercury.graph.ml.graph_features import GraphFeatures

# Init spark if available
if pyspark_installed:
    from pyspark.context import SparkContext
    from pyspark.sql import SparkSession
    sc = SparkContext.getOrCreate()
    spark = SparkSession(sc)
    from pyspark.sql.types import (
        StructType,
        StructField,
        StringType,
        IntegerType,
        FloatType
    )
    from pyspark.sql import functions as F

# Declare vertices, edges and GraphFeatures instance
v = spark.createDataFrame(
    [(0, 42, "42", 42), (1, None, "42", 42)],
    schema=StructType([
        StructField("id", IntegerType(), False),
        StructField("x1", IntegerType(), True),
        StructField("x2", StringType(), True),
        StructField("x3", IntegerType(), True)
    ])
)
e = spark.createDataFrame(
    [(0, 1, 1.0)],
    schema=StructType([
        StructField("src", IntegerType(), False),
        StructField("dst", IntegerType(), True),
        StructField('weight', FloatType(), True)
    ])
)
gf = GraphFeatures()


# _verify_vertices nulls
def test_verify_vertices_warns():
    with pytest.warns(UserWarning, match="Column 'x1' contains 1 null values"):
        gf._verify_vertices(vertices=v.select("id", "x1"))


# _verify_vertices dtypes
def test_verify_vertices_non_numeric_error():
    with pytest.raises(
        AssertionError, match="Non-numeric values found in column 'x2'"
    ):
        gf._verify_vertices(vertices=v.select("id", "x2"))


# _verify_edges (expected to pass)
def test_verify_vertices_success():
    try:
        gf._verify_vertices(v.select("id", "x3"))
    except AssertionError:
        pytest.fail("Valid vertices raised an unexpected AssertionError.")


# _verify_edges src
def test_verify_edges_src():
    with pytest.raises(AssertionError, match='Expected column "src" not in edges'):
        gf._verify_edges(e.select(F.col("src").alias("source"), "dst"))


# _verify_edges dst
def test_verify_edges_dst():
    with pytest.raises(AssertionError, match='Expected column "dst" not in edges'):
        gf._verify_edges(e.select("src", F.col("dst").alias("dest")))


# _verify_edges duplicates
def test_verify_edges_duplicates():
    with pytest.raises(
        AssertionError, match="edges contains 1 duplicated src-dst pairs"
    ):
        gf._verify_edges(e.unionByName(e))


# _verify_edges weight dtype
def test_verify_edges_weight_type():
    with pytest.raises(
        AssertionError,
        match='Column "weight" must be a float or an int. Received string instead',
    ):
        gf._verify_edges(e.select("src", "dst", F.lit("1").alias("weight")))


# _verify_edges weight dtype
def test_verify_edges_directed_graph():
    with pytest.raises(
        AssertionError,
        match="edges has mirrored edges. Directed graphs are not yet supported!",
    ):
        e_tmp = (
            e.unionByName(
                e.select(
                    F.col("dst").alias("src"), 
                    F.col("src").alias("dst"),
                    F.col("weight").alias("weight")
                )
            )
        )
        gf._verify_edges(
            e_tmp
        )


# _verify_edges (expected to pass)
def test_verify_edges_success():
    try:
        gf._verify_edges(e)
    except AssertionError:
        pytest.fail("Valid edges raised an unexpected AssertionError.")


@pytest.fixture
def dataset1():
    dataset = (
        spark
        .createDataFrame(
            [
                (1, 2, 1.0),
                (1, 3, 1.0),
                (1, 4, 1.0),
                (2, 3, 1.0),
                (2, 4, 1.0),
                (3, 4, 1.0),
                (3, 5, 1.0),
                (4, 5, 1.0),
                (4, 6, 1.0),
                (5, 6, 1.0),
                (6, 7, 1.0)
            ],
            schema=StructType([
                StructField('src', StringType(), False),
                StructField('dst', StringType(), False),
                StructField('weight', FloatType(), True)
            ])
        )
    )
    return dataset


@pytest.fixture
def dataset2():
    dataset = (
        spark
        .createDataFrame(
            [
                (1, 2, .7),
                (1, 3, .2),
                (1, 4, .1),
                (2, 3, .2),
                (2, 4, .1),
                (3, 4, .3),
                (3, 5, .3),
                (4, 5, .3),
                (4, 6, .2),
                (5, 6, .4),
                (6, 7, .2)
            ],
            schema=StructType([
                StructField('src', StringType(), False),
                StructField('dst', StringType(), False),
                StructField('weight', FloatType(), True)
            ])
        )
    )
    return dataset


@pytest.fixture
def dataset3():
    dataset = (
        spark
        .createDataFrame(
            [
                (1, 2, 1.0),
                (2, 3, 1.0),
                (3, 1, 1.0),
                (4, 5, 1.0),
                (5, 4, 1.0),
                (6, 6, 1.0)
            ],
            schema=StructType([
                StructField('src', StringType(), False),
                StructField('dst', StringType(), False),
                StructField('weight', FloatType(), True)
            ])
        )
    )
    return dataset


@pytest.fixture
def dataset4():
    dataset = (
        spark
        .createDataFrame(
            [
                (1, 2, .5),
                (2, 3, .5),
                (3, 1, .5),
                (4, 5, .5),
                (5, 4, .5),
                (6, 6, 1.0)
            ],
            schema=StructType([
                StructField('src', StringType(), False),
                StructField('dst', StringType(), False),
                StructField('weight', FloatType(), True)
            ])
        )
    )
    return dataset


@pytest.fixture
def dataset5():
    dataset = (
        spark
        .createDataFrame(
            [
                (0, 54, 27483.57, 0.0),
                (1, 44, 24308.68, 1.0),
                (2, 56, 28238.44, 0.0),
                (3, 70, 32615.15, 0.0),
                (4, 42, 23829.23, 0.0),
                (5, 55, 25123.12, 1.0),
                (6, 60, 29000.00, 0.0),
                (7, 45, 28815.45, 1.0),
                (8, 49, 30500.00, 1.0),
                (9, 36, 22013.78, 0.0),
            ],
            schema=StructType([
                StructField('id', IntegerType(), False),
                StructField('age', IntegerType(), False),
                StructField('income', FloatType(), False),
                StructField('is_bad', FloatType(), False),
            ])
        )
    )
    return dataset


@pytest.fixture
def dataset6():
    dataset = (
        spark
        .createDataFrame(
            [
                (1, 10, 1000, 0.1),
                (2, 20, 2000, 0.2),
                (3, 30, 3000, 0.3),
                (4, 40, 4000, 0.4),
                (5, 50, 5000, 0.5),
                (6, 60, 6000, 0.6),
                (7, 70, 7000, 0.7),
                (8, 80, 8000, 0.8),
                (9, 90, 9000, 0.9),
                (10, 36, 10000, 1.0),
            ],
            schema=StructType([
                StructField('id', IntegerType(), False),
                StructField('age', IntegerType(), False),
                StructField('income', IntegerType(), False),
                StructField('is_bad', FloatType(), False),
            ])
        )
    )
    return dataset


@pytest.mark.parametrize(
    'dataset_fixture',
    ['dataset1', 'dataset2', 'dataset3', 'dataset4']
)
@pytest.mark.parametrize('order_value,expected_error', [
    (-1, 'ge'),  # Error order must be greater than 0
    (0, 'ge'),  # Error order must be greater than 0
    (0.5, 'ie'),  # Error order must be integer
    (1, 'no'),  # No error expected
    (1.5, 'ie'),  # Error order must be integer
    (2, 'no'),  # No error expected
    (3, 'wr'),  # Expected warning memory issues
    (4, 'wr'),  # Expected warning memory issues
    (5, 'wr')  # Expected warning memory issues
])
def test_get_neighbors_order_warns(
    dataset_fixture,
    order_value,
    expected_error,
    request
):
    dataset = request.getfixturevalue(dataset_fixture)
    if expected_error == 'ge':
        with pytest.raises(
            AssertionError,
            match='order must be an integer greater than 0.'
        ):
            gf._get_neighbors(dataset, order=order_value)
    elif expected_error == 'ie':
        with pytest.raises(AssertionError, match='order must be an integer.'):
            gf._get_neighbors(dataset, order=order_value)
    elif expected_error == 'wr':
        with pytest.warns(
            UserWarning,
            match=f'order={order_value} may cause the process to be slow.'
        ):
            gf._get_neighbors(dataset, order=order_value)
    else:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            gf._get_neighbors(dataset, order=order_value)
        assert len(w) == 0


@pytest.mark.parametrize(
    'dataset_fixture_edges',
    ['dataset1', 'dataset2', 'dataset3', 'dataset4']
)
@pytest.mark.parametrize('dataset_fixture_vertices', ['dataset5', 'dataset6'])
@pytest.mark.parametrize('attributes,expected_error', [
    (5, 'lse'),  # Error attributes must be a list of strings
    ([5, 'age'], 'aise'),  # Error all items in attributes must be strings
    (['age', 'income', 'other'], 'aiee'),  # All items in attrs must exist in vertices
    (['age', 'income', 'is_bad'], 'no'),  # No error expected
])
def test_aggregate_messages_attr_warns(
    dataset_fixture_edges,
    dataset_fixture_vertices,
    attributes,
    expected_error,
    request
):
    edges = request.getfixturevalue(dataset_fixture_edges)
    vertices = request.getfixturevalue(dataset_fixture_vertices)
    g = Graph(
        data=edges,
        nodes=vertices,
        keys={
            "src": "src",
            "dst": "dst",
            "weight": "weight",
            }
        )
    if expected_error == 'lse':
        with pytest.raises(
            AssertionError,
            match='attributes must be a list of strings.'
        ):
            gf = GraphFeatures(attributes=attributes)
            gf.fit(g)
    elif expected_error == 'aise':
        with pytest.raises(
            AssertionError,
            match='All items in attributes must be strings.'
        ):
            gf = GraphFeatures(attributes=attributes)
            gf.fit(g)
    elif expected_error == 'aiee':
        with pytest.raises(
            AssertionError,
            match='All items in attributes must exist in vertices.'
        ):
            gf = GraphFeatures(attributes=attributes)
            gf.fit(g)
    else:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            gf = GraphFeatures(attributes=attributes)
            gf.fit(g)
        assert len(w) == 0


@pytest.mark.parametrize(
    'dataset_fixture_edges',
    ['dataset1', 'dataset2', 'dataset3', 'dataset4']
)
@pytest.mark.parametrize('dataset_fixture_vertices', ['dataset5', 'dataset6'])
@pytest.mark.parametrize('functions,expected_error', [
    ('mode', 'yes'),  # Error invalid aggregate function
    (['sum', 'avg', 'min'], 'no'),  # No error expected
])
def test_aggregate_messages_aggf_warns(
    dataset_fixture_edges,
    dataset_fixture_vertices,
    functions,
    expected_error,
    request
):
    edges = request.getfixturevalue(dataset_fixture_edges)
    vertices = request.getfixturevalue(dataset_fixture_vertices)
    g = Graph(
        data=edges,
        nodes=vertices,
        keys={
            "src": "src",
            "dst": "dst",
            "weight": "weight",
            }
        )
    msg = (
        'Invalid aggregation function. Please provide one or more of '
        'the following valid options: "sum", "min", "max", "avg" or "wavg".'
    )
    if expected_error == 'yes':
        with pytest.raises(AssertionError, match=msg):
            gf = GraphFeatures(agg_funcs=functions)
            gf.fit(g)
    else:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            gf = GraphFeatures(agg_funcs=functions)
            gf.fit(g)
        assert len(w) == 0
