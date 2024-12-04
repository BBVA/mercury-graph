require.undef('moebius');

define('moebius', ['d3'], function(d3) {
  /**
   * Maps each node category with the corresponding defined color
   *
   * @param {Object} graph
   * @param {string} instance_name
   * @param {Object} node_config
   * @param {Object} edge_config
   * @param {Boolean} stopSimulation
   */
  function draw(graph, instance_name, node_config, edge_config, stopSimulation) {
    /** ************************************
        *  PARAMETERS DEFINITION
        ***************************************/
    // Unique identifier of the display
    const graphSeed = getRandomInt(1, 100000000);
    const defaultNodeColors = d3.scaleOrdinal().range(d3.schemeCategory20);
    const defaultEdgeColors = d3.scaleOrdinal().range(d3.schemeCategory20);
    const baseRadius = 30; // minimum node radius
    const baseWidth = 4; // minimum edge width
    const baseNodeColor = '#2DCCCD'; // default color por nodes
    const baseEdgeColor = '#9C9C9C'; // default color por edges
    const baseNodeLimit = 20;
    const baseDepth = 1;
    const width = 850;
    const height = 850;
    const scales = {
      'linear': d3.scaleLinear,
      'power': d3.scalePow,
      'sqrt': d3.scaleSqrt,
      'log': d3.scaleLog,
    };

    // Display parameters (can be modified in Config menu)
    let nodeLabel = node_config['label'];
    let nodeCategory = node_config['color'];
    let nodeColors = node_config['color_palette'];
    let nodeSizeMapping = node_config['size'];
    let nodeSizeThresholds = node_config['size_thresholds'];
    let edgeLabel = edge_config['label'];
    let edgeCategory = edge_config['color'];
    let edgeColors = edge_config['color_palette'];
    let edgeSizeMapping = edge_config['size'];
    let edgeSizeThresholds = edge_config['size_thresholds'];
    let nodeScaleType = node_config['scale'] != null ? node_config['scale'] : 'linear';
    let edgeScaleType = edge_config['scale'] != null ? edge_config['scale'] : 'linear';
    let nodesColorChanged = false; // flags to be used in config when updating colors
    let edgesColorChanged = false;
    // const hideDisconnectedNodes = true;

    // General parameters (can be modified in Config menu)
    let nodeLimit = baseNodeLimit;
    let depth = baseDepth;

    const hiddenAttributes = ['vx', 'vy', 'x', 'y', 'index', 'fx', 'fy',
      'realCount', 'count', '_int_id', 'id',
      'source', 'target', '_linknum', '_inverse', '_is_hidden'];

    // boolean for automatic colors palette
    let automaticNodeColors = (nodeCategory != null && isEmpty(nodeColors));
    let automaticEdgeColors = (edgeCategory != null && isEmpty(edgeColors));

    // If nodeSizeThresholds is not given, but we have a nodeSizeMapping
    // column, we change dynamically the size of the nodes, taking the
    // max and min values from all nodes
    let automaticNodeThresholds = (nodeSizeThresholds.length === 0 && nodeSizeMapping != null);
    if (automaticNodeThresholds) {
      nodeSizeThresholds = updateSizeThresholds(graph.nodes, nodeSizeMapping);
    }
    let nodeScaler = createScaler(nodeSizeThresholds, baseRadius, nodeScaleType);

    // IDEM edges
    let automaticEdgeThresholds = (edgeSizeThresholds.length === 0 && edgeSizeMapping != null);
    if (automaticEdgeThresholds) {
      edgeSizeThresholds = updateSizeThresholds(graph.links, edgeSizeMapping);
    }
    let edgeScaler = createScaler(edgeSizeThresholds, baseWidth, edgeScaleType);

    function detectEnvironment() {
        if (typeof google !== 'undefined' && typeof google.colab !== 'undefined') {
            return 'google_colab';
        } else if (typeof Jupyter !== 'undefined' && typeof Jupyter.notebook !== 'undefined') {
            return 'jupyter_notebook';
        } else {
            alert("Moebius is currently only compatible with Google Colab and Jupyter Notebooks Classic (prior to v7)");
            return 'unknown';
        }
    }

    // Base-SVG object parameters
    const d3_select = detectEnvironment() === "google_colab" ? "body" : element.get(0);
    const externalDiv = d3.select(d3_select)
        .append('div')
        .attr('class', 'external-div');

    const svg = externalDiv.append('svg')
        .attr('class', 'graph-svg')
        .attr('viewBox', '0 0 1050 850')
        .call(d3.zoom().on('zoom', () => svg.attr('transform', d3.event.transform)))
        .on('dblclick.zoom', null)
        .append('g')
        .attr('id', 'transform-text');


    /** ************************************
        *    MAIN
        ***************************************/

    const simulation = createForceSimulation();
    startSimulation(simulation, graph);
    computeLinknum(graph.links);

    // Graph Objects creation
    const defs = svg.append('svg:defs');

    const backgroundNodes = svg.append('g').attr('class', 'background-nodes');
    const svgLinks = svg.append('g').attr('class', 'links');
    const svgNodes = svg.append('g').attr('class', 'nodes');

    let backgroundNode = createBackgroundNodes(graph);

    /* LINKS */
    let link = createLinks(svgLinks, graph);
    addLinkStyle(link);

    /* NODES */
    updateNodeCount(graph);
    let node = createNodes(svgNodes, graph);
    addNodeStyle(node, baseRadius);
    node.classed('initial-node', true);

    // Initialization of containers
    createMenuButtons();
    createSearchBar();
    appendMoebiusLogo();
    createInformationBox();
    const confMenu = createConfMenu();
    const filterMenu = createFilterMenu();
    const nodeCategoryContainer = createNodeLegend();
    const edgeCategoryContainer = createEdgeLegend();

    updateNodeLegend(graph);
    updateEdgeLegend(graph);

    if (stopSimulation) endSimulation(simulation);

    setInterval((d) => hideSmallLinkLabels(), 100);

    /** *****************************************
        *  FUNCTIONS - COLORS AND SIZES MAPPING
        *******************************************/
    /**
     * Maps each node category with the corresponding defined color
     *
     * @param {string} nodeCategory: Node category
     * @return {string} A color for each node
     */
    function computeNodeColors(nodeCategory) {
      if (nodeCategory != null) {
        if (automaticNodeColors) {
          return defaultNodeColors(nodeCategory);
        } else {
          if (nodeCategory in nodeColors) {
            return nodeColors[nodeCategory];
          } else {
            return baseNodeColor;
          }
        }
      } else {
        return baseNodeColor;
      }
    }

    /**
         * Maps each edge label with the corresponding defined color
         *
         * @param {string} edgeCategory: Edge Label
         * @return {string} A color for each edge
         */
    function computeEdgeColors(edgeCategory) {
      if (edgeCategory != null) {
        if (automaticEdgeColors) {
          return defaultEdgeColors(edgeCategory);
        } else {
          if (edgeCategory in edgeColors) {
            return edgeColors[edgeCategory];
          } else {
            return baseEdgeColor;
          }
        }
      } else {
        return baseEdgeColor;
      }
    }

    /**
     * Maps numeric parameters for defined column with corresponding node sizes
     *
     * @param {float} numericValue Numeric value for node size
     * @return {number}
     */
    function computeNodeSizes(numericValue) {
      if (nodeSizeMapping === null) {
        return baseRadius;
      } else if (numericValue == null || typeof numericValue !== 'number') {
        return baseRadius;
      } else {
        if (numericValue < nodeSizeThresholds[0]) {
          return baseRadius;
        } else if (numericValue > nodeSizeThresholds[1]) {
          return 2 * baseRadius;
        } else {
          return nodeScaler(numericValue);
        }
      }
    }

    /**
     * Compute the size of each edge as a function of a given attribute
     *
     * @param {number} numericValue Value of the selected attribute
     * @return {number}
     */
    function computeEdgeSizes(numericValue) {
      if (edgeSizeMapping === null) {
        return baseWidth;
      } else if (numericValue == null || typeof numericValue !== 'number') {
        return baseWidth;
      } else {
        if (numericValue < edgeSizeThresholds[0]) {
          return baseWidth;
        } else if (numericValue > edgeSizeThresholds[1]) {
          return 2 * baseWidth;
        } else {
          return edgeScaler(numericValue);
        }
      }
    }

    /**
     * Each time the graph changes, computes the thresholds of the size of
     * the nodes
     *
     * @param {Object} graphElements:
     * @param {Object} sizeMapping:
     * @return {array}
     */
    function updateSizeThresholds(graphElements, sizeMapping) {
      const sizes = graphElements.map((graphElement) => graphElement[sizeMapping])
          .filter((value) => typeof value === 'number');
      const nodeSizeThresholds = [d3.min(sizes), d3.max(sizes)];
      return nodeSizeThresholds;
    }

    /**
     * Returns a scale given a min size
     *
     * @param {array} sizeThresholds
     * @param {number} minSize
     * @param {string} scale
     * @return {d3.scale}
     */
    function createScaler(sizeThresholds, minSize, scale='linear') {
      return scales[scale]()
          .domain(sizeThresholds)
          .range([minSize, 2 * minSize]);
    }

    /**
     *
     */
    function recomputeNodeSizes() {
      backgroundNodes.selectAll('.background-node circle')
          .attr('r', (d) => computeNodeSizes(d[nodeSizeMapping]));

      svgNodes.selectAll('.node path')
          .attr('d', (node) => `M0,0 a1,1 0 0,0 ${2 * computeNodeSizes(node[nodeSizeMapping])}, 0`)
          .attr('transform', (node) => `rotate(-45 0 0) translate(-${computeNodeSizes(node[nodeSizeMapping])}, 0)`);

      svgNodes.selectAll('.node .inner-node-circle, .node .inner-node-background-circle')
          .attr('r', (d) => computeNodeSizes(d[nodeSizeMapping]));

      svgNodes.selectAll('.node .g-count')
          .attr('transform', function(node) {
            const parentCircleRadius = computeNodeSizes(node[nodeSizeMapping]);
            return `translate(${parentCircleRadius*(3/4)}, ${- parentCircleRadius*(3/4)})`;
          });

      link.selectAll('.link .inner-path-link')
          .each(function(d) {
            const color = computeEdgeColors(d[edgeCategory]);
            const markerSize = 4 * computeEdgeSizes(d[edgeSizeMapping]);
            let dstRadius = baseRadius;
            if (nodeSizeMapping !== undefined) {
              dstRadius = computeNodeSizes(d.target[nodeSizeMapping]);
            }
            d3.select(this).attr('marker-end', marker(color, markerSize, dstRadius));
          });
    }

    /**
     *
     */
    function recomputeEdgeSizes() {
      link.selectAll('.link .inner-path-link')
          .attr('stroke-width', (link) => computeEdgeSizes(link[edgeSizeMapping]))
          .each(function(d) {
            const color = computeEdgeColors(d[edgeCategory]);
            const markerSize = 4 * computeEdgeSizes(d[edgeSizeMapping]);
            let dstRadius = baseRadius;
            if (nodeSizeMapping !== undefined) {
              dstRadius = computeNodeSizes(d.target[nodeSizeMapping]);
            }
            d3.select(this).attr('marker-end', marker(color, markerSize, dstRadius));
          });
    }

    /** *****************************************
        *  FUNCTIONS - GRAPH OBJECTS CREATION
        *******************************************/

    /**
     * Creates a circle behind each node and edge that is going to be used
     * by the function that remarks neighbors on click
     * @param {Object} graph Updated graph object
     * @return {background-node}
     */
    function createBackgroundNodes(graph) {
      const backgroundNode = backgroundNodes.selectAll('.background-node')
          .data(graph.nodes)
          .enter()
          .append('g')
          .attr('class', 'background-node');
      backgroundNode.append('circle')
          .attr('fill', 'black')
          .attr('r', (node) => computeNodeSizes(node[nodeSizeMapping]));
      return backgroundNode;
    }

    /**
     * Creates the SVG objects for the nodes and links them to the corresponding graph data. It also
     * calls the function to add style properties to those SVG objects
     *
     * @param {svg} svg Parent svg where the nodes will be created
     * @param {Object} graph Graph data
     * @return {Object}
     */
    function createNodes(svg, graph) {
      const nodeData = svg
          .selectAll('.node')
          .data(graph.nodes)
          .enter().append('g')
          .attr('class', (node) => 'node ' + 'category-' + cleanCategoryStr(node[nodeCategory]))
          .call(d3.drag()
              .on('start', dragStarted)
              .on('drag', dragged)
              .on('end', dragEnded));

      return nodeData;
    }
    /**
     * Sets the style attributes for the nodes SVG objects. It also calls the event functions related to
     * the user interaction
     *
     * @param {svg} node SVG objects corresponding to the nodes
     * @param {int} baseRadius Radius of the node circles
     */
    function addNodeStyle(node, baseRadius) {
      const t = d3.transition()
          .duration(500);

      const gNode = node.append('g')
          .attr('class', 'g-node');

      gNode.append('circle')
          .attr('fill', 'white')
          .attr('class', 'inner-node-background-circle')
          .attr('r', (node) => computeNodeSizes(node[nodeSizeMapping]));

      gNode.append('circle')
          .attr('id', (d) => d.id)
          .attr('fill', (node) => computeNodeColors(node[nodeCategory]))
          .on('click', clickNode)
          .on('dblclick', (node) => doubleClickNode(node, nodeLimit, depth))
          .attr('class', 'inner-node-circle')
          .transition(t)
          .attr('r', (node) => computeNodeSizes(node[nodeSizeMapping]));

      gNode.append('path')
          .attr('d', (node) => `M0,0 a1,1 0 0,0 ${2 * computeNodeSizes(node[nodeSizeMapping])}, 0`)
          .attr('class', 'initial-node-circle')
          .attr('transform', (node) => `rotate(-45 0 0) translate(-${computeNodeSizes(node[nodeSizeMapping])}, 0)`)
          .attr('visibility', 'hidden');

      node.append('text')
          .attr('class', 'text-id')
          .attr('dy', '.35em')
          .text((node) => node[nodeLabel])
          .attr('title', (d) => d[nodeLabel]);

      const countCircle = node.append('g')
          .attr('class', 'g-count')
          .attr('transform', function(node) {
            const parentCircleRadius = computeNodeSizes(node[nodeSizeMapping]);
            return `translate(${parentCircleRadius*(3/4)}, ${- parentCircleRadius*(3/4)})`;
          })
          .style('visibility', (d) => (d.realCount > 0) ? 'visible' : 'hidden');

      countCircle.append('circle')
          .attr('class', 'circle-count')
          .attr('r', baseRadius / 2)
          .attr('fill', (node) => computeNodeColors(node[nodeCategory]));


      countCircle.append('text')
          .attr('class', 'text-count')
          .attr('dy', '.20em')
          .text((node) => (node.realCount <= 10000) ? node.realCount : '10k+')
          .attr('text-anchor', 'middle')
          .attr('fill', 'white');
    }

    /**
     * Creates the SVG objects for the links and links them to the corresponding graph data. It also
     * calls the function to add style properties to those SVG objects
     *
     * @param {svg} svg Parent svg where the links will be created
     * @param {Object} graph Graph data
     * @return {Object}
     */
    function createLinks(svg, graph) {
      const linkData = svg
          .selectAll('.link')
          .data(graph.links)
          .enter().append('g')
          .attr('class',
              (link) => `link edge-category-${cleanCategoryStr(link[edgeCategory])}
                         category-${cleanCategoryStr(link.source[nodeCategory])}
                         category-${cleanCategoryStr(link.target[nodeCategory])}`)
          .attr('id', (link) => link._int_id);
      return linkData;
    }
    /**
     * Sets the style attributes for the links SVG objects. It also calls the event functions related to
     * the user interaction
     *
     * @param {svg} link: SVG objects corresponding to the links
     */
    function addLinkStyle(link) {
      link.append('path')
          .attr('class', 'inner-path-link-textPath')
          .attr('id', (links) => `path-${links._int_id}-${graphSeed}`)
          .attr('stroke-width', 0)
          .attr('fill', 'none')
          .attr('stroke-opacity', 0)
          .attr('pointer-events', 'none');

      link.append('path')
          .attr('class', 'inner-path-link')
          .attr('stroke', (link) => computeEdgeColors(link[edgeCategory]))
          .attr('stroke-width', (link) => computeEdgeSizes(link[edgeSizeMapping]))
          .attr('fill', 'none')
          .attr('stroke-opacity', 1)
          .on('click', clickLink)
          .each(function(d) {
            const color = computeEdgeColors(d[edgeCategory]);
            const markerSize = 4 * computeEdgeSizes(d[edgeSizeMapping]);
            let dstRadius = baseRadius;
            if (nodeSizeMapping !== undefined) {
              dstRadius = computeNodeSizes(d.target[nodeSizeMapping]);
            }
            d3.select(this).attr('marker-end', marker(color, markerSize, dstRadius));
          });

      link.append('text')
          .attr('dy', '-10')
          .append('textPath')
          .attr('side', 'right')
          .attr('class', 'link-label-text')
          .attr('id', (links) => `#textPath-${links._int_id}-${graphSeed}`)
          .attr('xlink:href', (links) => `#path-${links._int_id}-${graphSeed}`)
          .style('font-size', '12px')
          .text((links) => links[edgeLabel])
          .style('opacity', 1.0)
          .attr('text-anchor', 'middle')
          .attr('startOffset', '50%')
          .attr('fill', (links) => computeEdgeColors(links[edgeCategory]));
    }
    /**
     * Creates the triangles for the links to convert them into an arrow
     *
     * @param {string} color  Link color
     * @param {number} markerSize
     * @param {number} dstRadius
     * @return {string}
     */
    function marker(color, markerSize, dstRadius) {
      const markerWidth = markerSize;
      const markerHeight = markerSize;
      defs.append('svg:marker')
          .attr('id', color.replace('#', '') + '/' + markerSize + '/' + dstRadius)
          .attr('viewBox', `0 ${-markerWidth/2} ${markerWidth} ${markerHeight}`)
          .attr('refX', dstRadius + markerHeight*0.8)
          .attr('refY', 0)
          // if different from viewBox width, both refX and real markerWidth are scaled
          .attr('markerWidth', markerWidth)
          // if different from viewBox height, both refY and real markerHeight are scaled
          .attr('markerHeight', markerHeight)
          .attr('orient', 'auto')
          .attr('markerUnits', 'userSpaceOnUse')
          .append('svg:path')
          .attr('d', `M0,${-markerWidth/2}L${markerHeight},0L0,${markerWidth/2}`)
          .style('fill', color);

      if (!color.includes('#')) {
        color = '#' + color;
      }

      return 'url(' + color + '/' + markerSize + '/' + dstRadius + ')';
    };

    /** *****************************************
        *  FUNCTIONS - CONNECTED NODES COMPUTING
        *******************************************/
    /**
     * Updates the realCount parameter in graph data after the graph changes
     *
     * @param {Object} graph
     */
    function updateNodeCount(graph) {
      graph.nodes.forEach(function(node) {
        const nodeDegree = graph.links
            .filter((link) => (link.source.id === node.id || link.target.id === node.id) &&
                                    (link.source.id !== link.target.id)).length;
        const autoDegree = graph.links
            .filter((link) => (link.source.id === link.target.id) &&
                                    (link.source.id === node.id)).length;
        node.realCount = node.count - nodeDegree - 2 * autoDegree;
      });

      externalDiv.selectAll('.text-count')
          .text((nodes) => (nodes.realCount <= 10000) ? nodes.realCount : '10k+');
      externalDiv.selectAll('.g-count')
          .style('visibility', (d) => (d.realCount > 0) ? 'visible' : 'hidden');
    }

    /**
     * Computes the information about the remaining connected nodes each time the graph changes
     * (new graph, expand and collapse)
     *
     * @param {Object} links Data related to the links information after the graph change
     */
    function computeLinknum(links) {
      const allLinkPairs = new Set();

      links.forEach(function(link) {
        if (link.source.id > link.target.id) {
          allLinkPairs.add([link.source.id, link.target.id]);
        } else {
          allLinkPairs.add([link.target.id, link.source.id]);
        }
      });

      allLinkPairs.forEach(function(linkPair) {
        links.filter(
            (link) => (link.source.id === linkPair[0] && link.target.id === linkPair[1]) ||
                            (link.source.id === linkPair[1] && link.target.id === linkPair[0]),
        ).forEach(function(link, i) {
          link._linknum = 5 * i;
          link._inverse = (link.source.id === linkPair[0]) ? 1 : -1;
        });
      });
    }

    /** *****************************************
        *  FUNCTIONS - INFO BOX CREATION
        *******************************************/

    /**
     * Creates the 'foreign objects' to fill the info box layout
     *
     * @return {svg}
     */
    function createInformationBox() {
      const infoContainer = externalDiv.append('div')
          .attr('class', 'info-container');

      infoContainer
          .append('div')
          .attr('id', 'information-container');

      /* BUTTONS */

      const buttonContainer = infoContainer.append('div')
          .attr('class', 'button-container');
      // .style('display', 'none')

      buttonContainer.append('button')
          .attr('type', 'button')
          .attr('class', 'expand-button')
          .append('svg')
          .attr('viewBox', '0 0 512 512')
          .attr('class', 'moebius-icon')
          .attr('title', 'Expand nodes')
          .html(expandIcon)
          .on('click',
              function() {
                externalDiv.select('#expand-prompt').remove();
                expandNodesWithPrompt();
              },
          );

      buttonContainer.append('button')
          .attr('type', 'button')
          .attr('class', 'collapse-button')
          .append('svg')
          .attr('title', 'Collapse nodes')
          .attr('viewBox', '0 0 512 512')
          .attr('class', 'moebius-icon')
          .html(collapseIcon)
          .on('click', function() {
            const markedNodes = svgNodes.selectAll('.marked').data();
            markedNodes.forEach((node) => collapseNode(node));
          });
      return infoContainer;
    }

    /**
     * Creates the element to introduce the legend text
     *
     * @return {div}
     */
    function createNodeLegend() {
      const externalLegendDiv = externalDiv.append('div')
          .attr('class', 'external-legend-div');

      const nodeLegendContainer = externalLegendDiv.append('div')
          .attr('class', 'legend-container')
          .attr('id', 'node-legend-container');

      const nodeLegendTitle = nodeLegendContainer.append('div')
          .attr('class', 'id-title');

      // Adding title to node legend
      nodeLegendTitle.append('text')
          .attr('class', 'box-title')
          .text('Node Legend')
          .style('cursor', 'pointer')
          .attr('title', 'Hide Legend')
          .on('click', function() {
            const categoryContainer = d3.select(this.parentNode.nextSibling);
            const isVisible = categoryContainer.style('display') === 'block';
            categoryContainer.style('display', (d) => (isVisible) ? 'none' : 'block');
          });

      // Adding a button to reset node legend
      nodeLegendTitle.append('button').attr('type', 'button')
          .attr('class', 'reset-legend-button')
          .append('svg')
          .attr('viewBox', '0 0 512 512')
          .attr('class', 'moebius-icon')
          .html(resetLegendIcon)
          .attr('title', 'Reset Legend')
          .on('click', resetNodeLegend);

      if (nodeCategory === undefined) {
        nodeLegendContainer.style('display', 'none');
      }

      const nodeCategoryContainer = nodeLegendContainer
          .append('div')
          .attr('class', 'category-container')
          .attr('id', 'node-category-container');

      return nodeCategoryContainer;
    }

    /**
     * Resets all category filters in node legend
     */
    function resetNodeLegend() {
      const HiddenCategories = getHiddenCategories('#node-legend-container');
      HiddenCategories.forEach(function(category) {
        filterNodeCategory(category);
      });
      const nodeLegendContainer = externalDiv.select('#node-legend-container');
      nodeLegendContainer
          .selectAll('.legend-svg')
          .classed('hidden-category', false);
    }

    /**
     * Creates the element to introduce the legend text
     *
     * @return {div}
     */
    function createEdgeLegend() {
      const externalLegendDiv = externalDiv.select('.external-legend-div');

      const edgeLegendContainer = externalLegendDiv.append('div')
          .attr('class', 'legend-container')
          .attr('id', 'edge-legend-container')
          .style('top', '280px');

      const edgeLegendTitle = edgeLegendContainer.append('div')
          .attr('class', 'id-title');

      // Adding title to edge legend
      edgeLegendTitle.append('text')
          .attr('class', 'box-title')
          .text('Edge Legend')
          .style('cursor', 'pointer')
          .attr('title', 'Hide Legend')
          .on('click', function() {
            const categoryContainer = d3.select(this.parentNode.nextSibling);
            const isVisible = categoryContainer.style('display') === 'block';
            categoryContainer.style('display', (d) => (isVisible) ? 'none' : 'block');
          });

      // Adding a button to reset edge legend
      edgeLegendTitle.append('button').attr('type', 'button')
          .attr('class', 'reset-legend-button')
          .append('svg')
          .attr('viewBox', '0 0 512 512')
          .attr('class', 'moebius-icon')
          .attr('title', 'Reset graph')
          .html(resetLegendIcon)
          .attr('title', 'Reset Legend')
          .on('click', resetEdgeLegend);

      if (edgeCategory === undefined) {
        edgeLegendContainer.style('display', 'none');
      }

      const edgeCategoryContainer = edgeLegendContainer
          .append('div')
          .attr('class', 'category-container')
          .attr('id', 'edge-category-container');

      return edgeCategoryContainer;
    }

    /**
     * Resets all category filters in edge legend
     */
    function resetEdgeLegend() {
      const HiddenCategories = getHiddenCategories('#edge-legend-container');
      HiddenCategories.forEach(function(category) {
        filterEdgeCategory(category);
      });
      const edgeLegendContainer = externalDiv.select('#edge-legend-container');
      edgeLegendContainer
          .selectAll('.legend-svg')
          .classed('hidden-category', false);
    }

    /**
     * Updates the legend information every time the graph changes
     *
     * @param {Object} graph: Graph data
     */
    function updateNodeLegend(graph) {
      const categories = new Set();
      graph.nodes.forEach((data) => categories.add(data[nodeCategory]));

      nodeCategoryContainer.selectAll('.legend-svg').remove();

      const legendItems = nodeCategoryContainer
          .selectAll('div')
          .data(Array.from(categories)).enter()
          .append('div')
          .attr('class', (category) => 'legend-svg ' + 'category-' + cleanCategoryStr(category))
          .on('click', (category) => filterNodeCategory(category));

      legendItems
          .append('svg')
          .style('width', 43)
          .style('height', 30)
          .append('circle')
          .attr('class', 'legend_circle')
          .attr('cx', 25)
          .attr('cy', 10)
          .attr('r', 10)
          .style('fill', (category) => computeNodeColors(category));

      legendItems.append('div')
          .append('text')
          .attr('class', 'legend-text')
          .text((category)=> category)
          .attr('title', (category) => category)
          .style('color', (category) => computeNodeColors(category));

      node.classed('hidden-node', false);
      link.classed('hidden-link', false);
    }

    /**
     * Updates the legend information every time the graph changes
     *
     * @param {Object} graph: Graph data
     */
    function updateEdgeLegend(graph) {
      const categories = new Set();
      graph.links.forEach((data) => categories.add(data[edgeCategory]));

      edgeCategoryContainer.selectAll('.legend-svg').remove();

      const legendItems = edgeCategoryContainer
          .selectAll('div')
          .data(Array.from(categories)).enter()
          .append('div')
          .attr('class', (category) => 'legend-svg ' + 'edge-category-' + cleanCategoryStr(category))
          .on('click', (category) => filterEdgeCategory(category));

      legendItems
          .append('svg')
          .style('width', 43)
          .style('height', 30)
          .append('rect')
          .attr('class', 'legend_circle')
          .attr('x', 15)
          .attr('y', 8)
          .attr('width', 20)
          .attr('height', 4)
          .style('fill', (category) => computeEdgeColors(category));

      legendItems.append('div')
          .append('text')
          .attr('class', 'legend-text')
          .text((category)=> category)
          .attr('title', (category) => category)
          .style('color', (category) => computeEdgeColors(category));

      link.classed('hidden-link', false);
    }

    /**
     * Returns which categories are hidden in a given legend
     *
     * @param {string} legendContainer
     * @return {Object} hiddenCategories
     */
    function getHiddenCategories(legendContainer) {
      const hiddenCategories = externalDiv.select(legendContainer)
          .selectAll('.legend-svg')
          .filter(function() {
            return this.classList.contains('hidden-category');
          })
          .data();
      return hiddenCategories;
    }

    /**
     * Hides all the nodes that belongs to the given category
     *
     * @param {string} category
     */
    function filterNodeCategory(category) {
      externalDiv.selectAll('.node, .link').classed('marked', false);
      // const visibleCategories = getVisibleCategories('#node-legend-container');
      const classCategory = '.category-' + cleanCategoryStr(category);
      const legendBox = externalDiv.select('#node-legend-container');
      // const legendEdges = externalDiv.select('#edge-legend-container');
      // We have to retrieve if the category is already hidden or not
      const isHidden = legendBox.select(classCategory)
          .classed('hidden-category');

      legendBox.selectAll(classCategory)
          .classed('hidden-category', !isHidden);

      svgNodes.selectAll(classCategory)
          .classed('hidden-node-category', !isHidden);

      updateHiddenNodesLinks();
      updateRemarkedNeighbors();
    }

    /**
     * Hides all the edges that belongs to the given category
     *
     * @param {string} category
     */
    function filterEdgeCategory(category) {
      externalDiv.selectAll('.node, .link').classed('marked', false);
      // const visibleCategories = getVisibleCategories('#node-legend-container');
      const classCategory = '.edge-category-' + cleanCategoryStr(category);
      const legendBox = externalDiv.select('#edge-legend-container');
      const isHidden = legendBox.select(classCategory)
          .classed('hidden-category');

      legendBox.selectAll(classCategory)
          .classed('hidden-category', !isHidden);

      const filteredLinks = svgLinks.selectAll(classCategory);
      // if (isHidden) {// to keep previously hidden links when turning from hidden to visible
      //   filteredLinks = filteredLinks.filter(function(link) { // filter to take into account hidden node categories
      //     // the link is displayed only when nodes from both sides are visible
      //     return (visibleCategories.includes(link.source[nodeCategory]) &&
      //                       visibleCategories.includes(link.target[nodeCategory]));
      //   });
      // }
      filteredLinks.classed('hidden-link-category', !isHidden);
      updateHiddenNodesLinks();
      updateRemarkedNeighbors();
    }

    /** *****************************************
        *  FUNCTIONS - SIMULATION
        *******************************************/
    /**
     * Generates a force layout so graph elements get distributed through the canvas
     *
     * @return {d3.simulation}
     */
    function createForceSimulation() {
      const simulation = d3.forceSimulation()
      // Sets the center of attraction for all nodes
          .force('x', d3.forceX(width / 2 + width / 8))
          .force('y', d3.forceY(height / 2))
      // Avoids nodes to collide generating a radial force
          .force('collide', d3.forceCollide(baseRadius + 2))
      // Generates repel forces between nodes to spread them through the canvas
          .force('charge', d3.forceManyBody().strength(-5000))
      // Generates link forces between connected nodes
          .force('link', d3.forceLink() .id((d) => d.id).distance(100));
      return simulation;
    }

    /**
     * Links the force layout with data from the graph, setting nodes and links dynamic parameters
     * (position, velocity...). It also calls 'ticked' function, which will define the update of nodes
     * dynamic parameters for each unit of time.
     *
     * @param {d3.simulation} simulation Output from createForceSimulation function
     * @param {Object} graph Graph data
     */
    function startSimulation(simulation, graph) {
      simulation
          .nodes(graph.nodes)
          .on('tick', ticked);
      simulation.force('link')
          .links(graph.links);
    }

    /**
     * Fixes node position when the simulation ends, so the graph remains still and can be moved
     * manually by the user
     *
     * @param {d3.simulation} simulation Output from 'createForceSimulation' function
     */
    function endSimulation(simulation) {
      simulation.on('end', function() {
        node.each(function(d) {
          d.fx = d.x;
          d.fy = d.y;
        });
      });
    }

    /**
     * Sets the dynamic parameters of the SVG objects for each unit of time, according to the simulation.
     */
    function ticked() {
      link.selectAll('.inner-path-link').attr('d', function(d) {
        if (d.target == d.source) {
          const x = d.source.x;
          const y = d.source.y;
          const r = 200 + d._linknum * 15;
          const dx = x - r;
          const dySup = y + r;
          const dyInf = y - r;
          return bezierCurve(x, y, dx, dyInf, dx, dySup, x, y);
        } else {
          const c1 = d.target.x - d.source.x;
          const c2 = d.target.y - d.source.y;
          const h = Math.sqrt(c1 * c1 + c2 * c2);
          const cos = c1 / h;
          const sin = c2 / h;
          const pointX = (d.target.x + d.source.x) / 2 + sin * 10 * d._linknum * d._inverse;
          const pointY = (d.target.y + d.source.y) / 2 - cos * 10 * d._linknum * d._inverse;
          return bezierCurve(d.source.x, d.source.y, pointX, pointY, pointX, pointY,
              d.target.x, d.target.y);
        }
      });

      link.selectAll('.inner-path-link-textPath').attr('d', function(d) {
        if (d.target == d.source) {
          const x = d.source.x;
          const y = d.source.y;
          const r = 200 + d._linknum * 15;
          const dx = x - r;
          const dySup = y + r;
          const dyInf = y - r;
          return bezierCurve(x, y, dx, dyInf, dx, dySup, x, y);
        } else {
          const c1 = d.target.x - d.source.x;
          const c2 = d.target.y - d.source.y;
          const h = Math.sqrt(c1 * c1 + c2 * c2);
          const cos = c1 / h;
          const sin = c2 / h;
          const pointX = (d.target.x + d.source.x) / 2 + sin * 10 * d._linknum * d._inverse;
          const pointY = (d.target.y + d.source.y) / 2 - cos * 10 * d._linknum * d._inverse;
          if (d.target.x < d.source.x) {
            return bezierCurve(d.target.x, d.target.y, pointX, pointY, pointX, pointY,
                d.source.x, d.source.y);
          } else {
            return bezierCurve(d.source.x, d.source.y, pointX, pointY, pointX, pointY,
                d.target.x, d.target.y);
          }
        }
      });

      node.attr('transform', function(d) {
        return 'translate(' + d.x + ',' + d.y + ')';
      });

      backgroundNode.attr('transform', function(d) {
        return 'translate(' + d.x + ',' + d.y + ')';
      });
    }

    /**
     * Creates a curved link given the required geometry parameters
     *
     * @param {int} xIni Coordinate X for starting point
     * @param {int} yIni Coordinate Y for starting point
     * @param {int} xRef1 Coordinate X for reference point 1
     * @param {int} yRef1 Coordinate Y for reference point 1
     * @param {int} xRef2 Coordinate X for reference point 2
     * @param {int} yRef2 Coordinate Y for reference point 2
     * @param {int} xEnd Coordinate X for end point
     * @param {int} yEnd Coordinate Y for end point
     * @return {string}
     */
    function bezierCurve(xIni, yIni, xRef1, yRef1,
        xRef2, yRef2, xEnd, yEnd) {
      return 'M' + xIni + ',' + yIni + 'C' + xRef1 + ',' + yRef1 +
                    ' ' + xRef2 + ',' + yRef2 + ' ' + xEnd + ',' + yEnd;
    }

    /** ************************************
        *  FUNCTIONS - EVENT HANDLING
        ***************************************/

    /**
     * Event function for the initial click when dragging a node
     */
    function dragStarted() {
      if (!d3.event.active) simulation.alphaTarget(0.3).restart();
      d3.event.subject.fx = d3.event.subject.x;
      d3.event.subject.fy = d3.event.subject.y;
    }

    /**
     * Event function to be executed when a node is being dragged
     */
    function dragged() {
      d3.event.subject.fx = d3.event.x;
      d3.event.subject.fy = d3.event.y;
    }

    /**
     * Event function for the 'unclick' when dragging a node
     */
    function dragEnded() {
      if (!d3.event.active) simulation.alphaTarget(0);
      if (stopSimulation) {
        d3.event.subject.fx = d3.event.x;
        d3.event.subject.fy = d3.event.y;
      } else {
        d3.event.subject.fx = null;
        d3.event.subject.fy = null;
      }
    }

    /**
     * Event function executed when the user clicks a node. The node is highlighted and the information about the node
     * attributes is shown within the info box.
     *
     * @param {node} d Information about the clicked node
     */
    function clickNode(d) {
      const thisNode = d3.select(this.parentNode.parentNode);
      const isMarked = thisNode.classed('marked');

      const containerBox = externalDiv.select('#information-container');
      containerBox.selectAll('*').remove();

      externalDiv.select('.expand-button').style('visibility', 'hidden');
      externalDiv.select('.collapse-button').style('visibility', 'visible');

      if (isMarked && d3.event.ctrlKey) {
        thisNode.classed('marked', false);
        updateRemarkedNeighbors();
        return;
      } else if (isMarked) {
        svg.selectAll('.node').classed('marked', false);
        externalDiv.select('.collapse-button').style('visibility', 'hidden');
        updateRemarkedNeighbors();
        return;
      }

      if (!d3.event.ctrlKey) {
        svg.selectAll('.node').classed('marked', false);
      }

      svg.selectAll('.link').classed('marked', false);

      thisNode.classed('marked', true);
      updateRemarkedNeighbors();

      if (d.realCount !== 0) {
        externalDiv.select('.expand-button').style('visibility', 'visible');
      }

      let data = [];

      for (const key in d) {
        if (d[key] !== null && !hiddenAttributes.includes(key)) {
          data = data.concat({'name': key, 'value': d[key]});
        }
      }

      containerBox.append('div')
          .attr('class', 'id-title')
          .append('text')
          .attr('class', 'box-title')
          .text(d.id);

      if (nodeCategory != null) {
        containerBox.append('div')
            .attr('title', 'Remark this category')
            .on('click', function() {
              nodeCategoryContainer.selectAll('.legend-svg').filter(function() {
                return ![...this.classList].some((d) => d.includes('hidden-category'));
              }).dispatch('click');
              filterNodeCategory(d[nodeCategory]);
            })
            .attr('class', 'parent-category-div ')
            .append('div')
            .style('height', '30px')
            .attr('class', 'category-div')

            .text(d[nodeCategory])
            .style('background', computeNodeColors(d[nodeCategory]));
      }


      const divs = containerBox.selectAll('.info-field')
          .data(data).enter()
          .append('div')
          .attr('class', 'info-field');

      divs.append('p').attr('class', 'field-title')
          .text((d) => d.name);

      divs.append('p').attr('class', 'field-content')
          .attr('title', (d) => d.value)
          .text((d) => d.value);
    }

    /**
     * Event function executed when the user clicks a link. The link is
     * highlighted and the information about the link
     * attributes is shown within the info box.
     *
     * @param {node} d: Information about the clicked link
     */
    function clickLink(d) {
      const thisLink = d3.select(this.parentNode);
      const isMarked = thisLink.classed('marked');

      const containerBox = externalDiv.select('#information-container');
      containerBox.selectAll('*').remove();

      if (isMarked) {
        thisLink.classed('marked', false);
        return;
      }

      svg.selectAll('.link, .node').classed('marked', false);
      thisLink.classed('marked', true);

      // const hiddenAttributes = ['vx', 'vy', 'x', 'y', 'index', 'fx', 'fy',
      //   'source', 'target', 'id', '_linknum',
      //   '_int_id', 'inverse'];

      let data = [];
      for (const key in d) {
        if (d[key] !== null && !hiddenAttributes.includes(key)) {
          data = data.concat({'name': key, 'value': d[key]});
        }
      }

      containerBox.append('div')
          .attr('class', 'id-title')
          .append('h1')
          .text(d.source.id + '-' + d.target.id)
          .style('font-size', '15px');

      const divs = containerBox.selectAll('.info-field')
          .data(data).enter()
          .append('div')
          .attr('class', 'info-field');

      divs.append('p').attr('class', 'field-title')
          .text((d) => d.name);

      divs.append('p').attr('class', 'field-content')
          .attr('title', (d) => d.value)
          .text((d) => d.value);
      updateRemarkedNeighbors();
    }

    /**
     * Hides link labels when the user zooms out above a threshold
     *
     * @param {Object} d graph data
     */
    function hideSmallLinkLabels() {
      const transformText = externalDiv.select('#transform-text').attr('transform');
      const scaleFactor = transformText ? parseFloat(transformText.match(/scale\((.*?)\)/)[1]) : 1;
      if (scaleFactor < 0.8) {
        link.selectAll('.link-label-text').attr('visibility', 'hidden');
      } else {
        link.selectAll('.link-label-text').attr('visibility', 'visible');
      }
    }

    /** *****************************************
        *  FUNCTIONS - EXPAND AND COLLAPSE NODES
        *******************************************/

    /**
     * Renders a prompt to select limit and depth parameters to perform the
     * expand of a node.
     *
     */
    function expandNodesWithPrompt() {
      // We add a blocker div to prevent the use of the rest of the html while
      // the expand prompt is on display
      const blocker = externalDiv.append('div')
          .attr('class', 'blocker');

      const prompt = externalDiv.append('div')
          .attr('class', 'custom-prompt')
          .attr('id', 'expand-prompt');

      const form = prompt.append('form');

      prompt.append('button').attr('type', 'button')
          .attr('class', 'close-menu-button')
          .append('svg')
          .attr('viewBox', '0 0 512 512')
          .attr('class', 'moebius-icon')
          .html(closeMenuIcon)
          .attr('title', 'Close prompt')
          .on('click', function() {
            blocker.remove();
            prompt.remove();
          });

      form.append('label')
          .attr('for', 'node-limit')
          .text(`Nodes to expand`);

      form.append('input')
          .attr('type', 'number')
          .attr('id', 'node-limit')
          // .attr('name', 'node-limit')
          .attr('value', baseNodeLimit);

      form.append('label')
          .attr('for', 'node-depth')
          .text('Depth to expand');

      form.append('input')
          .attr('type', 'number')
          .attr('id', 'node-depth')
          // .attr('name', 'node-depth')
          .attr('value', baseDepth);

      prompt.append('button')
          .attr('class', 'moebius-button')
          .text('Apply')
          .on('click', function() {
            const nodeLimit = parseInt(externalDiv.select('input#node-limit').node().value);
            const depth = parseInt(externalDiv.select('input#node-depth').node().value);

            externalDiv.select('.custom-prompt').remove();
            const markedNodes = svgNodes.selectAll('.marked').data();
            markedNodes.forEach((node) => expandNode(node.id, nodeLimit, depth));
            blocker.remove();
          });
    }

    /**
     * Fetch all the neighbors from the given node, with a maximum number of
     * nodeLimit neighbors for each node and with a the given depth.
     *
     * @param {Object} nodeID
     * @param {number} nodeLimit
     * @param {number} depth
     */
    function expandNode(nodeID, nodeLimit = baseNodeLimit, depth = baseDepth) {
      const nodeID_param = typeof nodeID === "number" ? nodeID : `'${nodeID}'`;
      executePython(`${instance_name}._get_adjacent_nodes_moebius(${nodeID_param}, ${nodeLimit}, depth=${depth})`)
          .then((result) => managePythonOutput(result));
    }

    /**
     * Calls instance_name._get_adjacent_nodes_moebius for a given node ID to
     * draw it. If it does not find this node, prints an error message.
     *
     * @param {Object} nodeID
     * @param {number} nodeLimit
     * @param {number} depth
     */
    function searchNewNode(nodeID, nodeLimit = baseNodeLimit, depth = baseDepth) {
      const nodeID_param = typeof nodeID === "number" ? nodeID : `'${nodeID}'`;
      executePython(`${instance_name}._get_adjacent_nodes_moebius(${nodeID_param}, ${nodeLimit}, depth=${depth})`)
          .then((result) => {
            const emptyResult = `'{"nodes": [], "links": []}'`;
            if (result === emptyResult) {
              externalDiv.select('#node-not-found-div').remove();
              const customPrompt = externalDiv.append('div')
                  .attr('id', 'node-not-found-div')
                  .attr('class', 'custom-prompt')
                  .style('height', 'auto');

              customPrompt.append('div').append('text').text(`Node ${nodeID} not found`);

              customPrompt.append('button')
                  .attr('class', 'apply-button')
                  .text('Ok')
                  .on('click', function() {
                    customPrompt.remove();
                  });
            } else {
              managePythonOutput(result);
            }
          });
    }

    /**
     * Creates the new graph data depending on the selected node to be expanded
     *
     * @param {Object} node Information about the clicked node
     * @param {number} nodeLimit
     * @param {number} depth
     */
    function doubleClickNode(node, nodeLimit = baseNodeLimit, depth = baseDepth) {
      if (node.realCount !== 0) {
        expandNode(node.id, nodeLimit, depth);
      }
    }

    /**
     * Filters the newGraph object to delete all the information that is already
     * drawn.
     *
     * @param {array} graphIds
     * @param {Object} newGraph
     * @return {Object}
     */
    function computeNewNodesLinks(graphIds, newGraph) {
      newGraph.nodes = newGraph.nodes.filter((item) => !graphIds.nodes.has(item._int_id));
      newGraph.links = newGraph.links.filter((item) => !graphIds.links.has(item._int_id));

      return newGraph;
    }

    /**
     * Appends all the new links that have been fetched when expanding a node
     *
     * @param {Object} linksTotal
     */
    function updateLinks(linksTotal) {
      // Apply the general update pattern to the links.
      const allLinks = svgLinks.selectAll('.link')
          .data(linksTotal, (d) => d._int_id);
      allLinks.exit().remove();

      const updatedLinks = allLinks.enter()
          .append('g')
          .attr('class',
              (link) => `link edge-category-${cleanCategoryStr(link[edgeCategory])}
                         category-${cleanCategoryStr(link.source[nodeCategory])}
                         category-${cleanCategoryStr(link.target[nodeCategory])}`)
          .attr('id', (link) => link._int_id);

      addLinkStyle(updatedLinks);

      link = allLinks.merge(updatedLinks);
    }

    /**
     * Appends all the new nodes that have been fetched when expanding a node
     *
     * @param {Object} nodesTotal
     */
    function updateNodes(nodesTotal) {
      // Updating background circle
      const allBackgroundNodes = backgroundNodes.selectAll('.background-node')
          .data(nodesTotal, (d) => d._int_id);
      allBackgroundNodes.exit().remove();
      const updatedBackgroundNodes = allBackgroundNodes.enter()
          .append('g')
          .attr('class', 'background-node');

      updatedBackgroundNodes.append('circle')
          .attr('fill', 'black')
          .attr('r', (node) => computeNodeSizes(node[nodeSizeMapping]));

      backgroundNode = allBackgroundNodes.merge(updatedBackgroundNodes);

      // Apply the general update pattern to the nodes.
      const allNodes = svgNodes.selectAll('.node')
          .data(nodesTotal, (d) => d._int_id);

      allNodes.exit().remove();

      const updatedNodes = allNodes.enter()
          .append('g')
          .attr('class', (node) => 'node ' + 'category-' + cleanCategoryStr(node[nodeCategory]))
          .call(d3.drag()
              .on('start', dragStarted)
              .on('drag', dragged)
              .on('end', dragEnded),
          );

      addNodeStyle(updatedNodes, baseRadius);

      node = allNodes.merge(updatedNodes);
    }

    /**
     * Restarts the simulation
     *
     * @param {Object} graph
     */
    function updateSimulation(graph) {
      simulation.nodes(graph.nodes);
      simulation.force('link').links(graph.links);
      simulation.alpha(1).restart();
    }

    /**
     * Creates the new graph data depending on the selected node to be expanded
     *
     * @param {json} newGraph: New graph data to be displayed after expand operation
     *
     */
    function drillDown(newGraph) {
      const graphIds = computeGraphIds(graph);

      newGraph = computeNewNodesLinks(graphIds, newGraph);

      graph.nodes = graph.nodes.concat(newGraph.nodes);
      graph.links = graph.links.concat(newGraph.links);

      // Update and restart the simulation.
      updateSimulation(graph);

      if (automaticNodeThresholds) {
        // If automaticNodeThresholds we need to recompute the node
        // scaler to adjust all nodes to the new values
        nodeSizeThresholds = updateSizeThresholds(graph.nodes, nodeSizeMapping);
        nodeScaler = createScaler(nodeSizeThresholds, baseRadius, nodeScaleType);
        recomputeNodeSizes(graph);
      }

      if (automaticEdgeThresholds) {
        // If automaticEdgeThresholds we need to recompute the edges
        // scaler to adjust all edges to the new values
        edgeSizeThresholds = updateSizeThresholds(graph.links, edgeSizeMapping);
        edgeScaler = createScaler(edgeSizeThresholds, baseWidth, edgeScaleType);
        recomputeEdgeSizes(graph);
      }

      updateLinks(graph.links);
      updateNodes(graph.nodes);

      computeLinknum(graph.links);
      updateNodeCount(graph);

      const nodeHiddenCategories = getHiddenCategories('#node-legend-container');
      const edgeHiddenCategories = getHiddenCategories('#edge-legend-container');

      updateNodeLegend(graph);
      updateEdgeLegend(graph);
      updateRemarkedNeighbors();
      updateHiddenNodesLinks();
      updateFilterMenu(filterMenu);
      updateConfigMenu(confMenu);

      // We have to restore all the categories that were hidden
      nodeHiddenCategories.forEach((category) => filterNodeCategory(category));
      edgeHiddenCategories.forEach((category) => filterEdgeCategory(category));
    }

    /**
     * Function used by collapse node. Given the current graph and a node id,
     * returns the graph object with the given node neighbours deleted.
     *
     * @param {string} nodeID
     * @param {Object} graph
     * @return {Object}
     */
    function removeAdjacentNodes(nodeID, graph) {
      // This is a hash table that given a node id returns which are the
      // ids of the adjacent nodes
      const adjacentNodesTable = createAdjacentNodesTable(graph);
      const adjacentNodes = adjacentNodesTable[nodeID];

      const nodesToRemove = new Set();

      adjacentNodes.forEach(function(e) {
        const nodesNotTakenIntoAccount = new Set([nodeID, e, ...Array.from(adjacentNodes)]);
        const newSet = setDiff(adjacentNodesTable[e], nodesNotTakenIntoAccount);

        if (newSet.size === 0) {
          nodesToRemove.add(e);
        }
      });

      graph.nodes = graph.nodes.filter((node) => !nodesToRemove.has(node.id));
      graph.links = graph.links.filter(
          (link) => !nodesToRemove.has(link.source.id) && !nodesToRemove.has(link.target.id),
      );

      return graph;
    }

    /**
     * Creates the new graph data depending on the selected node to be collapsed
     *
     * @param {Object} inputNode
     */
    function collapseNode(inputNode) {
      graph = removeAdjacentNodes(inputNode.id, graph);

      // Update and restart the simulation.
      updateSimulation(graph);

      const backgroundNode = backgroundNodes.selectAll('.background-node')
          .data(graph.nodes, (d) => d._int_id);
      backgroundNode.exit().remove();

      // Apply the general update pattern to the links.
      const link = svgLinks.selectAll('.link')
          .data(graph.links, (d) => d._int_id);
      link.exit().remove();

      // Apply the general update pattern to the nodes.
      const node = svgNodes.selectAll('.node')
          .data(graph.nodes, (d) => d._int_id);
      node.exit().remove();

      if (automaticNodeThresholds) {
        nodeSizeThresholds = updateSizeThresholds(graph.nodes, nodeSizeMapping);
        nodeScaler = createScaler(nodeSizeThresholds, baseRadius, nodeScaleType);
        recomputeNodeSizes(graph);
      }

      if (automaticEdgeThresholds) {
        edgeSizeThresholds = updateSizeThresholds(graph.links, edgeSizeMapping);
        edgeScaler = createScaler(edgeSizeThresholds, baseWidth, edgeScaleType);
        recomputeEdgeSizes(graph);
      }

      updateNodeCount(graph);
      const nodeHiddenCategories = getHiddenCategories('#node-legend-container');
      const edgeHiddenCategories = getHiddenCategories('#edge-legend-container');

      updateNodeLegend(graph);
      updateEdgeLegend(graph);
      updateFilterMenu(filterMenu);
      updateConfigMenu(confMenu);
      updateHiddenNodesLinks();

      // We have to restore all the categories that were hidden
      nodeHiddenCategories.forEach((category) => filterNodeCategory(category));
      edgeHiddenCategories.forEach((category) => filterEdgeCategory(category));
    }

    /** *****************************************
        *  FUNCTIONS - PYTHON-JAVASCRIPT CONNECTION
        *******************************************/

    /**
     * Connects javascript with Python kernel and executes the given python code
     *
     * @param {string} python Python code to be executed
     * @return {Promise}
     */
    function executePython(python) {
      return new Promise((resolve, reject) => {
        if (detectEnvironment() === "google_colab") {
          google.colab.kernel.invokeFunction("notebook.colab_execute_python", [`${python}`], {})
            .then(response => {
              const output = response.data['text/plain'];
              resolve(output);
          })
          .catch(error => {
            reject(error);
          });
        } else if (detectEnvironment() === "jupyter_notebook") {
          const callbacks = {
            iopub: {
              output: (data) => ((data.content.data != null) ? resolve(data.content.data['text/plain']) :
                                reject(data.content.ename + '\n' + data.content.evalue + '\n' + data.content.traceback)),
            },
          };
          Jupyter.notebook.kernel.execute(`${python}`, callbacks, {
            silent: false,
            store_history: false,
            stop_on_error: true,
          });
        }
      });
    }

    /**
     * Given the result of the executePython function, manages if it is needed
     * to raise an exception or the result is corrected and can execute the
     * drillDown function
     *
     * @param {string} pythonOutput
     */
    function managePythonOutput(pythonOutput) {
      if (pythonOutput.includes('[ERROR]')) {
        alert(pythonOutput);
      } else {
        try {
          // We delete ' from python output
          pythonOutput = pythonOutput.substring(1, pythonOutput.length - 1);
          pythonOutput = cleanJSONString(pythonOutput);
          drillDown(JSON.parse(pythonOutput));
        } catch (error) {
          alert(error);
        }
      }
    }

    /**
     * Cleans a string to avoid errors when converting to json
     *
     * @param {string} s
     * @return {string}
     */
    function cleanJSONString(s) {
      s = s.replace(/\\n/g, '\\n')
          .replace(/\\'/g, '\\\'')
          .replace(/\\"/g, '\\"')
          .replace(/\\&/g, '\\&')
          .replace(/\\r/g, '\\r')
          .replace(/\\t/g, '\\t')
          .replace(/\\b/g, '\\b')
          .replace(/\\f/g, '\\f')
          .replace(/\\/g, '');
      // remove non-printable and other non-valid JSON chars
      s = s.replace(/[\u0000-\u0019]+/g, '');
      return s;
    }

    /* UTILS */

    /**
     * Returns an object that contains the unique ids of nodes and links.
     *
     * @param {Object} graph
     * @return {Object}
     */
    function computeGraphIds(graph) {
      const graphIds = {
        'nodes': new Set(),
        'links': new Set(),
      };

      graph.nodes.forEach((item) => graphIds.nodes.add(item._int_id));
      graph.links.forEach((item) => graphIds.links.add(item._int_id));

      return graphIds;
    }

    /**
     * Computes the different between two sets
     *
     * @param {Set} a
     * @param {Set} b
     * @return {Set}
     */
    function setDiff(a, b) {
      const difference = new Set(
          [...a].filter((x) => !b.has(x)));
      return difference;
    }

    /**
     * For each selected node, remarks each node neighbors an
     * its adjacent edges
     *
     */
    function updateRemarkedNeighbors() {
      // We first reset all the active classes
      svg.selectAll('.link').classed('active', false);
      svg.selectAll('.background-node').classed('active', false);

      // We need to select which classes are marked, and then apply
      // remarkNodeNeighborOnClick to update them
      const markedNodes = svgNodes.selectAll('.marked').data();
      markedNodes.forEach((node) => {
        remarkNodeNeighborOnClick(node);
      });
    }

    /**
     * Given a link, remarks its adjacent nodes.
     *
     * @param {Object} d
     */
    function remarkLinkNeighborOnClick(d) {
      externalDiv.selectAll('.background-node').classed('active', function(p) {
        return d3.select(this).classed('active') || p === d.source || p === d.target;
      });
    }

    /**
     * Given a node, remarks its adjacent nodes and edges
     *
     * @param {Object} d
     */
    function remarkNodeNeighborOnClick(d) {
      externalDiv.selectAll('.link').filter(function() {
        return !this.classList.contains('hidden-link');
      }).classed('active', function(p) {
        return d3.select(this).classed('active') || p.source === d || p.target === d;
      });
      externalDiv.selectAll('.link.active').each(function(d) {
        remarkLinkNeighborOnClick(d);
      });
      // thisNode.classed('active', true);
    }

    /**
     * Returns a random integer between min (inclusive) and max (inclusive).
     * The value is no lower than min (or the next integer greater than min
     * if min isn't an integer) and no greater than max (or the next integer
     * lower than max if max isn't an integer).
     * Using Math.round() will give you a non-uniform distribution!
     *
     * @param {number} min
     * @param {number} max
     * @return {number}
     */
    function getRandomInt(min, max) {
      min = Math.ceil(min);
      max = Math.floor(max);
      return Math.floor(Math.random() * (max - min + 1)) + min;
    }

    /**
     * Returns whether an object is empty or not
     *
     * @param {Object} obj
     * @return {Boolean}
     */
    function isEmpty(obj) {
      for (const key in obj) {
        if (obj.hasOwnProperty(key)) {
          return false;
        }
      }
      return true;
    }

    /**
     * Computes a hash table which each key is a node and each value is the set
     * of the key node adjacent nodes.
     *
     * @param {Object} graph
     * @return {Object}
     */
    function createAdjacentNodesTable(graph) {
      const links = graph.links;
      const adjacentNodesTable = {};
      links.forEach(function(d) {
        const sourceID = d.source.id;
        const targetID = d.target.id;
        if (sourceID in adjacentNodesTable) {
          adjacentNodesTable[sourceID].add(targetID);
        } else {
          adjacentNodesTable[sourceID] = new Set([targetID]);
        }

        if (targetID in adjacentNodesTable) {
          adjacentNodesTable[targetID].add(sourceID);
        } else {
          adjacentNodesTable[targetID] = new Set().add(sourceID);
        }
      });
      return adjacentNodesTable;
    }

    /** ********************
     * CONFIG MENU
     **********************/

    /**
     * Generates the configuration menu
     *
     * @return {div}
     */
    function createConfMenu() {
      // Main div
      const confMenu = externalDiv.append('div')
          .attr('class', 'conf-menu')
          .style('display', 'none');

      // Header
      confMenu.append('div')
          .attr('class', 'box-title')
          .style('padding', '5px')
          .text('Configuration');

      confMenu.append('button')
          .attr('type', 'button')
          .attr('class', 'close-menu-button')
          .append('svg')
          .attr('viewBox', '0 0 512 512')
          .attr('class', 'moebius-icon')
          .html(closeMenuIcon)
          .attr('title', 'Close Menu')
          .on('click', function() {
            confMenu.style('display', 'none');
          });

      // Tabs
      const tab = confMenu.append('div')
          .attr('class', 'tab');

      tab.append('button')
          .attr('class', 'tab-button')
          .attr('id', 'general-tab-button')
          .text('General')
          .classed('active', true)
          .on('click', function() {
            confMenu.selectAll('.tab-content')
                .style('display', 'none');
            confMenu.select('#general-tab-content')
                .style('display', 'block');
            confMenu.selectAll('.tab-button')
                .classed('active', false);
            confMenu.select('#general-tab-button')
                .classed('active', true);
          });

      tab.append('button')
          .attr('class', 'tab-button')
          .attr('id', 'node-tab-button')
          .text('Nodes')
          .on('click', function() {
            confMenu.selectAll('.tab-content')
                .style('display', 'none');
            confMenu.select('#node-tab-content')
                .style('display', 'block');
            confMenu.selectAll('.tab-button')
                .classed('active', false);
            confMenu.select('#node-tab-button')
                .classed('active', true);
          });

      tab.append('button')
          .attr('class', 'tab-button')
          .attr('id', 'edge-tab-button')
          .text('Edges')
          .on('click', function() {
            confMenu.selectAll('.tab-content')
                .style('display', 'none');
            confMenu.select('#edge-tab-content')
                .style('display', 'block');
            confMenu.selectAll('.tab-button')
                .classed('active', false);
            confMenu.select('#edge-tab-button')
                .classed('active', true);
          });

      // GENERAL CONTENT
      const generalTabContent = confMenu.append('div')
          .attr('class', 'tab-content')
          .attr('id', 'general-tab-content')
          .style('display', 'block');

      // Double Clicking
      generalTabContent.append('p')
          .attr('class', 'menu-subtitle')
          .text('Double-clicking');

      generalTabContent.append('div')
          .attr('class', 'menu-description')
          .text('Max # nodes to expand when double-clicking:');

      generalTabContent.append('input')
          .attr('class', 'menu-number')
          .attr('id', 'general-limit-number')
          .attr('type', 'number')
          .attr('min', 1)
          .attr('step', 1);

      generalTabContent.append('div')
          .attr('class', 'menu-description')
          .text('Depth level to expand when double-clicking:');

      generalTabContent.append('input')
          .attr('class', 'menu-number')
          .attr('id', 'general-depth-number')
          .attr('type', 'number')
          .attr('min', 1)
          .attr('step', 1);

      // Hide elements menu

      generalTabContent.append('p')
          .attr('class', 'menu-subtitle')
          .text('Hide elements');

      // Hide legend

      /**
       * Appends to parentElement a checkbox with the given label that hides all
       * elements that contains the elementClass given when checked.
       *
       * @param {Object} parentElement
       * @param {String} elementClass
       * @param {String} label
       */
      function hideClassWithCheckboxFactory(parentElement, elementClass, label) {
        const hideDiv = parentElement.append('div')
            .attr('class', 'menu-checkbox');

        hideDiv.append('input')
            .attr('type', 'checkbox')
            .on('change', function() {
              if (this.checked) {
                externalDiv.select(`.${elementClass}`)
                    .style('display', 'none');
              } else {
                externalDiv.select(`.${elementClass}`)
                    .style('display', 'block');
              }
            });

        hideDiv.append('label')
            .attr('class', 'label-radio')
            .text(label);
      }

      hideClassWithCheckboxFactory(generalTabContent, 'external-legend-div', 'Hide legends');

      hideClassWithCheckboxFactory(generalTabContent, 'search-bar', 'Hide search bar');

      hideClassWithCheckboxFactory(generalTabContent, 'info-container', 'Hide attribute menu');


      // NODES CONTENT
      const nodesTabContent = confMenu.append('div')
          .attr('class', 'tab-content')
          .attr('id', 'node-tab-content')
          .style('display', 'none');

      // Label
      nodesTabContent.append('p')
          .attr('class', 'menu-subtitle')
          .text('Label');
      nodesTabContent.append('select')
          .attr('class', 'menu-dropdown')
          .attr('id', 'node-label-dropdown');

      // Color
      nodesTabContent.append('p')
          .attr('class', 'menu-subtitle')
          .text('Color');

      nodesTabContent.append('select')
          .attr('class', 'menu-dropdown')
          .attr('id', 'node-color-dropdown')
          .on('change', function() {
            nodesColorChanged = true; // flag to check when node colors change. If true, filters and legend will be reset when press Apply
            // color categories update
            confMenu.select('#node-color-palette').node().innerHTML = '';
            const nodeSelectedColumn = confMenu.select('#node-color-dropdown').node().value;
            const nodeCategories = new Set();
            graph.nodes.forEach((data) => nodeCategories.add(data[nodeSelectedColumn]));
            for (const category of nodeCategories) {
              const nodeColorItem = confMenu.select('#node-color-palette').append('div');
              nodeColorItem.append('input')
                  .attr('class', 'color-selector')
                  .attr('type', 'color')
                  .attr('value', baseNodeColor);
              nodeColorItem.append('label')
                  .attr('class', 'color-label')
                  .text(category);
            }
            confMenu.select('#node-color-checkbox').select('input').node().checked = false;
          });

      nodesTabContent.append('div')
          .attr('class', 'menu-checkbox')
          .attr('id', 'node-color-checkbox');

      confMenu.select('#node-color-checkbox').append('input')
          .attr('type', 'checkbox')
          .on('change', function() {
            nodesColorChanged = true; // flag to check when node colors change. If true, legend will be updated when press Apply
            const nodeColorLabels = confMenu.select('#node-color-palette').selectAll('.color-label').nodes();
            const nodeColorSelectors = confMenu.select('#node-color-palette').selectAll('.color-selector').nodes();
            if (this.checked === true) {
              for (let i = 0; i < nodeColorLabels.length; i++) {
                nodeColorSelectors[i].disabled = true;
                nodeColorSelectors[i].value = defaultNodeColors(nodeColorLabels[i].textContent);
              }
            } else {
              for (let i = 0; i < nodeColorLabels.length; i++) {
                nodeColorSelectors[i].disabled = false;
                nodeColorSelectors[i].value = baseNodeColor;
              }
            }
          });

      confMenu.select('#node-color-checkbox').append('label')
          .attr('class', 'label-radio')
          .text('Automatic color palette');

      nodesTabContent.append('div')
          .attr('id', 'node-color-palette');

      // Size
      nodesTabContent.append('p')
          .attr('class', 'menu-subtitle')
          .text('Size');

      nodesTabContent.append('select')
          .attr('class', 'menu-dropdown')
          .attr('id', 'node-size-dropdown')
          .on('change', function() {
            // size thresholds update
            const nodeDropdownValue = confMenu.select('#node-size-dropdown').node().value;
            const nodeRangeLimits = updateSizeThresholds(graph.nodes, nodeDropdownValue);
            confMenu.select('#node-min-threshold').node().innerHTML = nodeRangeLimits[0];
            confMenu.select('#node-max-threshold').node().innerHTML = nodeRangeLimits[1];
          });

      nodesTabContent.append('div')
          .attr('class', 'menu-checkbox')
          .attr('id', 'node-size-checkbox');

      confMenu.select('#node-size-checkbox').append('input')
          .attr('type', 'checkbox')
          .on('change', function() {
            if (this.checked === false) {
              confMenu.select('#node-size-number-min').node().disabled = false;
              confMenu.select('#node-size-number-max').node().disabled = false;
            } else {
              confMenu.select('#node-size-number-min').node().disabled = true;
              confMenu.select('#node-size-number-max').node().disabled = true;
              confMenu.select('#node-size-number-min').node().value = '';
              confMenu.select('#node-size-number-max').node().value = '';
            }
          });

      confMenu.select('#node-size-checkbox').append('label')
          .attr('class', 'label-radio')
          .text('Automatic size scaling');

      nodesTabContent.append('div')
          .attr('class', 'menu-description')
          .text('Min Threshold (auto): ')
          .append('span')
          .attr('id', 'node-min-threshold');

      nodesTabContent.append('input')
          .attr('class', 'menu-number')
          .attr('id', 'node-size-number-min')
          .attr('type', 'number');

      nodesTabContent.append('div')
          .attr('class', 'menu-description')
          .text('Max Threshold (auto): ')
          .append('span')
          .attr('id', 'node-max-threshold');

      nodesTabContent.append('input')
          .attr('class', 'menu-number')
          .attr('id', 'node-size-number-max')
          .attr('type', 'number');

      nodesTabContent.append('div')
          .attr('id', 'node-size-radio')
          .attr('class', 'menu-radio-button');

      for (const scale of Object.keys(scales)) {
        confMenu.select('#node-size-radio').append('input')
            .attr('id', 'node-scale-' + scale)
            .attr('type', 'radio')
            .attr('name', 'node-scale')
            .attr('value', scale);
        confMenu.select('#node-size-radio').append('label')
            .attr('class', 'label-radio')
            .text(scale);
      };

      // EDGES CONTENT
      const edgesTabContent = confMenu.append('div')
          .attr('class', 'tab-content')
          .attr('id', 'edge-tab-content')
          .style('display', 'none');

      // Label
      edgesTabContent.append('p')
          .attr('class', 'menu-subtitle')
          .text('Label');
      edgesTabContent.append('select')
          .attr('class', 'menu-dropdown')
          .attr('id', 'edge-label-dropdown');

      // Color
      edgesTabContent.append('p')
          .attr('class', 'menu-subtitle')
          .text('Color');

      edgesTabContent.append('select')
          .attr('class', 'menu-dropdown')
          .attr('id', 'edge-color-dropdown')
          .on('change', function() {
            edgesColorChanged = true; // flag to check when edge colors change. If true, filters and legend will be reset when press Apply
            // color categories update
            confMenu.select('#edge-color-palette').node().innerHTML = '';
            const edgeSelectedColumn = confMenu.select('#edge-color-dropdown').node().value;
            const edgeCategories = new Set();
            graph.links.forEach((data) => edgeCategories.add(data[edgeSelectedColumn]));
            for (const category of edgeCategories) {
              const edgeColorItem = confMenu.select('#edge-color-palette').append('div');
              edgeColorItem.append('input')
                  .attr('class', 'color-selector')
                  .attr('type', 'color')
                  .attr('value', baseEdgeColor);
              edgeColorItem.append('label')
                  .attr('class', 'color-label')
                  .text(category);
            }
            confMenu.select('#edge-color-checkbox').select('input').node().checked = false;
          });

      edgesTabContent.append('div')
          .attr('class', 'menu-checkbox')
          .attr('id', 'edge-color-checkbox');

      confMenu.select('#edge-color-checkbox').append('input')
          .attr('type', 'checkbox')
          .on('change', function() {
            edgesColorChanged = true; // flag to check when edge colors change. If true, legend will be updated when press Apply
            const edgeColorLabels = confMenu.select('#edge-color-palette').selectAll('.color-label').nodes();
            const edgeColorSelectors = confMenu.select('#edge-color-palette').selectAll('.color-selector').nodes();
            if (this.checked === true) {
              for (let i = 0; i < edgeColorLabels.length; i++) {
                edgeColorSelectors[i].disabled = true;
                edgeColorSelectors[i].value = defaultEdgeColors(edgeColorLabels[i].textContent);
              }
            } else {
              for (let i = 0; i < edgeColorLabels.length; i++) {
                edgeColorSelectors[i].disabled = false;
                edgeColorSelectors[i].value = baseEdgeColor;
              }
            }
          });

      confMenu.select('#edge-color-checkbox').append('label')
          .attr('class', 'label-radio')
          .text('Automatic color palette');

      edgesTabContent.append('div')
          .attr('id', 'edge-color-palette');

      // Size
      edgesTabContent.append('p')
          .attr('class', 'menu-subtitle')
          .text('Size');

      edgesTabContent.append('select')
          .attr('class', 'menu-dropdown')
          .attr('id', 'edge-size-dropdown')
          .on('change', function() {
            // size thresholds update
            const edgeDropdownValue = confMenu.select('#edge-size-dropdown').node().value;
            const edgeRangeLimits = updateSizeThresholds(graph.links, edgeDropdownValue);
            confMenu.select('#edge-min-threshold').node().innerHTML = edgeRangeLimits[0];
            confMenu.select('#edge-max-threshold').node().innerHTML = edgeRangeLimits[1];
          });

      edgesTabContent.append('div')
          .attr('class', 'menu-checkbox')
          .attr('id', 'edge-size-checkbox');

      confMenu.select('#edge-size-checkbox').append('input')
          .attr('type', 'checkbox')
          .on('change', function() {
            if (this.checked === false) {
              confMenu.select('#edge-size-number-min').node().disabled = false;
              confMenu.select('#edge-size-number-max').node().disabled = false;
            } else {
              confMenu.select('#edge-size-number-min').node().disabled = true;
              confMenu.select('#edge-size-number-max').node().disabled = true;
              confMenu.select('#edge-size-number-min').node().value = '';
              confMenu.select('#edge-size-number-max').node().value = '';
            }
          });

      confMenu.select('#edge-size-checkbox').append('label')
          .attr('class', 'label-radio')
          .text('Automatic size scaling');

      edgesTabContent.append('div')
          .attr('class', 'menu-description')
          .text('Min Threshold (auto): ')
          .append('span')
          .attr('id', 'edge-min-threshold');

      edgesTabContent.append('input')
          .attr('class', 'menu-number')
          .attr('id', 'edge-size-number-min')
          .attr('type', 'number');

      edgesTabContent.append('div')
          .attr('class', 'menu-description')
          .text('Max Threshold (auto): ')
          .append('span')
          .attr('id', 'edge-max-threshold');

      edgesTabContent.append('input')
          .attr('class', 'menu-number')
          .attr('id', 'edge-size-number-max')
          .attr('type', 'number');

      edgesTabContent.append('div')
          .attr('id', 'edge-size-radio')
          .attr('class', 'menu-radio-button');

      for (const scale of Object.keys(scales)) {
        confMenu.select('#edge-size-radio').append('input')
            .attr('id', 'edge-scale-' + scale)
            .attr('type', 'radio')
            .attr('name', 'edge-scale')
            .attr('value', scale);
        confMenu.select('#edge-size-radio').append('label')
            .attr('class', 'label-radio')
            .text(scale);
      };

      // APPLY and OK buttons
      let applyButtons = confMenu.append('div')
        .attr('class', 'apply-buttons')

      applyButtons.append('button')
        .text('Apply')
        .on('click', updateConfigParameters);

      applyButtons.append('button')
        .text('OK')
        .on('click', okButton);

      updateConfigMenu(confMenu);
      return confMenu;
    }

    /**
     * Fills the configuration menu with the current graph information
     *
     * @param {Object} confMenu
     */
    function updateConfigMenu(confMenu) {
      // update of general tab values
      confMenu.select('#general-limit-number').node().value = nodeLimit;
      confMenu.select('#general-depth-number').node().value = depth;

      // update of node attributes within the displayed graph
      const nodeAttributes = {};
      svgNodes.selectAll('.node').data().forEach(function(d) {
        for (const key in d) {
          if (d[key] !== null && !hiddenAttributes.includes(key)) {
            if (nodeAttributes.hasOwnProperty(key)) {
              nodeAttributes[key] = nodeAttributes[key].concat(d[key]);
            } else {
              nodeAttributes[key] = [d[key]];
            }
          }
        }
      });
      const nodeFields = (Object.keys(nodeAttributes));
      nodeFields.unshift('id');
      nodeFields.unshift('-- Select Attribute --');

      // update of edge attributes within the displayed graph
      const edgeAttributes = {};
      svgLinks.selectAll('.link').data().forEach(function(d) {
        for (const key in d) {
          if (d[key] !== null && !hiddenAttributes.includes(key)) {
            if (edgeAttributes.hasOwnProperty(key)) {
              edgeAttributes[key] = edgeAttributes[key].concat(d[key]);
            } else {
              edgeAttributes[key] = [d[key]];
            }
          }
        }
      });
      const edgeFields = (Object.keys(edgeAttributes));
      edgeFields.unshift('-- Select Attribute --')

      // node dropdowns update
      confMenu.select('#node-label-dropdown').node().innerHTML = '';
      confMenu.select('#node-color-dropdown').node().innerHTML = '';
      confMenu.select('#node-size-dropdown').node().innerHTML = '';
      for (const val of nodeFields) {
        confMenu.select('#node-label-dropdown').append('option')
            .attr('value', val)
            .text(val);
        confMenu.select('#node-color-dropdown').append('option')
            .attr('value', val)
            .text(val);
        confMenu.select('#node-size-dropdown').append('option')
            .attr('value', val)
            .text(val);
      }
      if (nodeLabel !== undefined) {
        confMenu.select('#node-label-dropdown').node().value = nodeLabel;
      } else {
        confMenu.select('#node-label-dropdown').node().value = '-- Select Attribute --';
      }
      if (nodeCategory !== undefined) {
        confMenu.select('#node-color-dropdown').node().value = nodeCategory;
      } else {
        confMenu.select('#node-color-dropdown').node().value = '-- Select Attribute --';
      }
      if (nodeSizeMapping !== undefined) {
        confMenu.select('#node-size-dropdown').node().value = nodeSizeMapping;
      } else {
        confMenu.select('#node-size-dropdown').node().value = '-- Select Attribute --';
      }

      // edge dropdowns update
      confMenu.select('#edge-label-dropdown').node().innerHTML = '';
      confMenu.select('#edge-color-dropdown').node().innerHTML = '';
      confMenu.select('#edge-size-dropdown').node().innerHTML = '';
      for (const val of edgeFields) {
        confMenu.select('#edge-label-dropdown').append('option')
            .attr('value', val)
            .text(val);
        confMenu.select('#edge-color-dropdown').append('option')
            .attr('value', val)
            .text(val);
        confMenu.select('#edge-size-dropdown').append('option')
            .attr('value', val)
            .text(val);
      }

      if (edgeLabel !== undefined) {
        confMenu.select('#edge-label-dropdown').node().value = edgeLabel;
      } else {
        confMenu.select('#edge-label-dropdown').node().value = '-- Select Attribute --';
      }
      if (edgeCategory !== undefined) {
        confMenu.select('#edge-color-dropdown').node().value = edgeCategory;
      } else {
        confMenu.select('#edge-color-dropdown').node().value = '-- Select Attribute --';
      }
      if (edgeSizeMapping !== undefined) {
        confMenu.select('#edge-size-dropdown').node().value = edgeSizeMapping;
      } else {
        confMenu.select('#edge-size-dropdown').node().value = '-- Select Attribute --';
      }

      // node color categories update
      nodesColorChanged = false
      confMenu.select('#node-color-palette').node().innerHTML = '';
      const nodeSelectedColumn = confMenu.select('#node-color-dropdown').node().value;
      const nodeCategories = new Set();
      graph.nodes.forEach((data) => nodeCategories.add(data[nodeSelectedColumn]));
      for (const category of nodeCategories) {
        const nodeColorItem = confMenu.select('#node-color-palette').append('div');
        nodeColorItem.append('input')
            .attr('class', 'color-selector')
            .attr('type', 'color')
            .on('change', function() {
              nodesColorChanged = true; // flag to check when node colors change. If true, filters and legend will be reset when press Apply
            });
        nodeColorItem.append('label')
            .attr('class', 'color-label')
            .text(category);
      }
      const nodeColorLabels = confMenu.select('#node-color-palette').selectAll('.color-label').nodes();
      const nodeColorSelectors = confMenu.select('#node-color-palette').selectAll('.color-selector').nodes();
      if (automaticNodeColors) {
        confMenu.select('#node-color-checkbox').select('input').node().checked = true;
        for (let i = 0; i < nodeColorLabels.length; i++) {
          nodeColorSelectors[i].disabled = true;
          nodeColorSelectors[i].value = defaultNodeColors(nodeColorLabels[i].textContent);
        }
      } else {
        confMenu.select('#node-color-checkbox').select('input').node().checked = false;
        for (let i = 0; i < nodeColorLabels.length; i++) {
          nodeColorSelectors[i].disabled = false;
          nodeColorSelectors[i].value = computeNodeColors(nodeColorLabels[i].textContent);
        }
      }

      // edge color categories update
      edgesColorChanged = false;
      confMenu.select('#edge-color-palette').node().innerHTML = '';
      const edgeSelectedColumn = confMenu.select('#edge-color-dropdown').node().value;
      const edgeCategories = new Set();
      graph.links.forEach((data) => edgeCategories.add(data[edgeSelectedColumn]));
      for (const category of edgeCategories) {
        const edgeColorItem = confMenu.select('#edge-color-palette').append('div');
        edgeColorItem.append('input')
            .attr('class', 'color-selector')
            .attr('type', 'color')
            .on('change', function() {
              edgesColorChanged = true; // flag to check when edge colors change. If true, filters and legend will be reset when press Apply
            });
        edgeColorItem.append('label')
            .attr('class', 'color-label')
            .text(category);
      }
      const edgeColorLabels = confMenu.select('#edge-color-palette').selectAll('.color-label').nodes();
      const edgeColorSelectors = confMenu.select('#edge-color-palette').selectAll('.color-selector').nodes();
      if (automaticEdgeColors) {
        confMenu.select('#edge-color-checkbox').select('input').node().checked = true;
        for (let i = 0; i < edgeColorLabels.length; i++) {
          edgeColorSelectors[i].disabled = true;
          edgeColorSelectors[i].value = defaultEdgeColors(edgeColorLabels[i].textContent);
        }
      } else {
        confMenu.select('#edge-color-checkbox').select('input').node().checked = false;
        for (let i = 0; i < edgeColorLabels.length; i++) {
          edgeColorSelectors[i].disabled = false;
          edgeColorSelectors[i].value = colourNameToHex(computeEdgeColors(edgeColorLabels[i].textContent));
        }
      }

      // node size thresholds update
      const nodeRangeLimits = updateSizeThresholds(graph.nodes, confMenu.select('#node-size-dropdown').node().value);
      confMenu.select('#node-min-threshold').node().innerHTML = nodeRangeLimits[0];
      confMenu.select('#node-max-threshold').node().innerHTML = nodeRangeLimits[1];
      if (automaticNodeThresholds) {
        confMenu.select('#node-size-checkbox').select('input').node().checked = true;
        confMenu.select('#node-size-number-min').node().disabled = true;
        confMenu.select('#node-size-number-max').node().disabled = true;
        confMenu.select('#node-size-number-min').node().value = '';
        confMenu.select('#node-size-number-max').node().value = '';
      } else {
        confMenu.select('#node-size-checkbox').select('input').node().checked = false;
        confMenu.select('#node-size-number-min').node().disabled = false;
        confMenu.select('#node-size-number-max').node().disabled = false;
        confMenu.select('#node-size-number-min').node().value = nodeSizeThresholds[0];
        confMenu.select('#node-size-number-max').node().value = nodeSizeThresholds[1];
      }


      // edge size thresholds update
      const edgeRangeLimits = updateSizeThresholds(graph.links, confMenu.select('#edge-size-dropdown').node().value);
      confMenu.select('#edge-min-threshold').node().innerHTML = edgeRangeLimits[0];
      confMenu.select('#edge-max-threshold').node().innerHTML = edgeRangeLimits[1];
      if (automaticEdgeThresholds) {
        confMenu.select('#edge-size-checkbox').select('input').node().checked = true;
        confMenu.select('#edge-size-number-min').node().disabled = true;
        confMenu.select('#edge-size-number-max').node().disabled = true;
        confMenu.select('#edge-size-number-min').node().value = '';
        confMenu.select('#edge-size-number-max').node().value = '';
      } else {
        confMenu.select('#edge-size-checkbox').select('input').node().checked = false;
        confMenu.select('#edge-size-number-min').node().disabled = false;
        confMenu.select('#edge-size-number-max').node().disabled = false;
        confMenu.select('#edge-size-number-min').node().value = edgeSizeThresholds[0];
        confMenu.select('#edge-size-number-max').node().value = edgeSizeThresholds[1];
      }

      // scales update (not impacted by graph changes)
      for (const scale of Object.keys(scales)) {
        if (scale === nodeScaleType) {
          confMenu.select('#node-scale-' + scale).node().checked = true;
        }
        if (scale === edgeScaleType) {
          confMenu.select('#edge-scale-' + scale).node().checked = true;
        }
      }
    }

    /**
     * Applies to the current graph the parameters filled in the config menu
     *
     */
    function updateConfigParameters() {
      // general params update
      nodeLimit = parseInt(confMenu.select('#general-limit-number').node().value);
      depth = parseInt(confMenu.select('#general-depth-number').node().value);

      // node label update
      nodeLabel = confMenu.select('#node-label-dropdown').node().value;
      svgNodes.selectAll('.text-id')
          .text((node) => node[nodeLabel])
          .attr('title', (d) => d[nodeLabel]);

      // edge label update
      edgeLabel = confMenu.select('#edge-label-dropdown').node().value;
      svgLinks.selectAll('.link-label-text')
          .text((links) => links[edgeLabel]);

      // node color update
      if (edgesColorChanged || nodesColorChanged) { // reset of both edge and node category filtering prior to color change
        resetNodeLegend();
        resetEdgeLegend();
      };
      nodeCategory = confMenu.select('#node-color-dropdown').node().value;
      automaticNodeColors = confMenu.select('#node-color-checkbox').select('input').node().checked;
      svgNodes.selectAll('.node').each(function(node) { // update node category classes
        const thisNode = d3.select(this);
        const classList = [...this.classList];
        const oldNodeCategory = classList.filter((cl) => cl.startsWith('category-'))[0];
        const newNodeCategory = 'category-' + cleanCategoryStr(node[nodeCategory]);
        thisNode.classed(oldNodeCategory, false);
        thisNode.classed(newNodeCategory, true);
      });
      svgLinks.selectAll('.link').each(function(edge) { // update edge category classes
        const thisEdge = d3.select(this);
        const classList = [...this.classList];
        const oldNodeCategories = classList.filter((cl) => cl.startsWith('category-'));
        const newNodeCategories = ['category-' + cleanCategoryStr(edge.source[nodeCategory]),
          'category-' + cleanCategoryStr(edge.target[nodeCategory])];
        for (let i = 0; i < oldNodeCategories.length; i++) {
          thisEdge.classed(oldNodeCategories[i], false);
          thisEdge.classed(newNodeCategories[i], true);
        }
      });
      nodeColors = {};
      const nodeColorLabels = confMenu.select('#node-color-palette').selectAll('.color-label').nodes();
      const nodeColorSelectors = confMenu.select('#node-color-palette').selectAll('.color-selector').nodes();
      for (let i = 0; i < nodeColorLabels.length; i++) {
        nodeColors[nodeColorLabels[i].textContent] = nodeColorSelectors[i].value;
      }
      if (nodeCategory !== '') {
        externalDiv.select('#node-legend-container').style('display', 'block');
      }
      svgNodes.selectAll('.inner-node-circle')
          .attr('fill', (node) => computeNodeColors(node[nodeCategory]));
      svgNodes.selectAll('.circle-count')
          .attr('fill', (node) => computeNodeColors(node[nodeCategory]));
      if (edgesColorChanged || nodesColorChanged) { // legend updates only when color has been changed, otherwise it would reset filters all the time
        updateNodeLegend(graph);
      };

      // edge color update
      if (edgesColorChanged || nodesColorChanged) { // reset of both edge and node category filtering prior to color change
        resetNodeLegend();
        resetEdgeLegend();
      };
      edgeCategory = confMenu.select('#edge-color-dropdown').node().value;
      automaticEdgeColors = confMenu.select('#edge-color-checkbox').select('input').node().checked;
      svgLinks.selectAll('.link').each(function(edge) { // update edge category classes
        const thisEdge = d3.select(this);
        const classList = [...this.classList];
        const oldEdgeCategory = classList.filter((cl) => cl.startsWith('edge-category-'))[0];
        const newEdgeCategory = 'edge-category-' + cleanCategoryStr(edge[edgeCategory]);
        thisEdge.classed(oldEdgeCategory, false);
        thisEdge.classed(newEdgeCategory, true);
      });
      edgeColors = {};
      const edgeColorLabels = confMenu.select('#edge-color-palette').selectAll('.color-label').nodes();
      const edgeColorSelectors = confMenu.select('#edge-color-palette').selectAll('.color-selector').nodes();
      for (let i = 0; i < edgeColorLabels.length; i++) {
        edgeColors[edgeColorLabels[i].textContent] = edgeColorSelectors[i].value;
      }
      if (edgeCategory !== '') {
        externalDiv.select('#edge-legend-container').style('display', 'block');
      }
      svgLinks.selectAll('.inner-path-link')
          .attr('stroke', (link) => computeEdgeColors(link[edgeCategory]));
      svgLinks.selectAll('.link-label-text')
          .attr('fill', (link) => computeEdgeColors(link[edgeCategory]));
      if (edgesColorChanged || nodesColorChanged) { // legend updates only when color has been changed, otherwise it would reset filters all the time
        updateEdgeLegend(graph);
      };

      // node size update
      nodeSizeMapping = confMenu.select('#node-size-dropdown').node().value;
      automaticNodeThresholds = confMenu.select('#node-size-checkbox').select('input').node().checked;
      if (automaticNodeThresholds) {
        nodeSizeThresholds[0] = Number(confMenu.select('#node-min-threshold').node().innerHTML);
        nodeSizeThresholds[1] = Number(confMenu.select('#node-max-threshold').node().innerHTML);
      } else {
        nodeSizeThresholds[0] = Number(confMenu.select('#node-size-number-min').node().value);
        nodeSizeThresholds[1] = Number(confMenu.select('#node-size-number-max').node().value);
      }

      for (const scale of Object.keys(scales)) {
        if (confMenu.select('#node-scale-' + scale).node().checked === true) {
          nodeScaleType = confMenu.select('#node-scale-' + scale).node().value;
        }
      }
      nodeScaler = createScaler(nodeSizeThresholds, baseRadius, nodeScaleType);
      recomputeNodeSizes();

      // edge size update
      edgeSizeMapping = confMenu.select('#edge-size-dropdown').node().value;
      automaticEdgeThresholds = confMenu.select('#edge-size-checkbox').select('input').node().checked;
      if (automaticEdgeThresholds) {
        edgeSizeThresholds[0] = Number(confMenu.select('#edge-min-threshold').node().innerHTML);
        edgeSizeThresholds[1] = Number(confMenu.select('#edge-max-threshold').node().innerHTML);
      } else {
        edgeSizeThresholds[0] = Number(confMenu.select('#edge-size-number-min').node().value);
        edgeSizeThresholds[1] = Number(confMenu.select('#edge-size-number-max').node().value);
      }

      for (const scale of Object.keys(scales)) {
        if (confMenu.select('#edge-scale-' + scale).node().checked === true) {
          edgeScaleType = confMenu.select('#edge-scale-' + scale).node().value;
        }
      }
      edgeScaler = createScaler(edgeSizeThresholds, baseWidth, edgeScaleType);
      recomputeEdgeSizes();

      const configCheck = [nodeLimit, depth,
        nodeLabel, nodeCategory, nodeSizeMapping,
        automaticNodeColors, nodeColors,
        automaticNodeThresholds, nodeSizeThresholds, nodeScaleType,
        edgeLabel, edgeCategory, edgeSizeMapping,
        automaticEdgeColors, edgeColors,
        automaticEdgeThresholds, edgeSizeThresholds, edgeScaleType];
      console.log(configCheck)
    }

    function okButton() {
      updateConfigParameters();
      confMenu.style('display', 'none');
    }

    function colourNameToHex(colour) {
      var colours = {"aliceblue":"#f0f8ff","antiquewhite":"#faebd7","aqua":"#00ffff","aquamarine":"#7fffd4","azure":"#f0ffff",
      "beige":"#f5f5dc","bisque":"#ffe4c4","black":"#000000","blanchedalmond":"#ffebcd","blue":"#0000ff","blueviolet":"#8a2be2","brown":"#a52a2a","burlywood":"#deb887",
      "cadetblue":"#5f9ea0","chartreuse":"#7fff00","chocolate":"#d2691e","coral":"#ff7f50","cornflowerblue":"#6495ed","cornsilk":"#fff8dc","crimson":"#dc143c","cyan":"#00ffff",
      "darkblue":"#00008b","darkcyan":"#008b8b","darkgoldenrod":"#b8860b","darkgray":"#a9a9a9","darkgreen":"#006400","darkkhaki":"#bdb76b","darkmagenta":"#8b008b","darkolivegreen":"#556b2f",
      "darkorange":"#ff8c00","darkorchid":"#9932cc","darkred":"#8b0000","darksalmon":"#e9967a","darkseagreen":"#8fbc8f","darkslateblue":"#483d8b","darkslategray":"#2f4f4f","darkturquoise":"#00ced1",
      "darkviolet":"#9400d3","deeppink":"#ff1493","deepskyblue":"#00bfff","dimgray":"#696969","dodgerblue":"#1e90ff",
      "firebrick":"#b22222","floralwhite":"#fffaf0","forestgreen":"#228b22","fuchsia":"#ff00ff",
      "gainsboro":"#dcdcdc","ghostwhite":"#f8f8ff","gold":"#ffd700","goldenrod":"#daa520","gray":"#808080","green":"#008000","greenyellow":"#adff2f",
      "honeydew":"#f0fff0","hotpink":"#ff69b4",
      "indianred ":"#cd5c5c","indigo":"#4b0082","ivory":"#fffff0","khaki":"#f0e68c",
      "lavender":"#e6e6fa","lavenderblush":"#fff0f5","lawngreen":"#7cfc00","lemonchiffon":"#fffacd","lightblue":"#add8e6","lightcoral":"#f08080","lightcyan":"#e0ffff","lightgoldenrodyellow":"#fafad2",
      "lightgrey":"#d3d3d3","lightgreen":"#90ee90","lightpink":"#ffb6c1","lightsalmon":"#ffa07a","lightseagreen":"#20b2aa","lightskyblue":"#87cefa","lightslategray":"#778899","lightsteelblue":"#b0c4de",
      "lightyellow":"#ffffe0","lime":"#00ff00","limegreen":"#32cd32","linen":"#faf0e6",
      "magenta":"#ff00ff","maroon":"#800000","mediumaquamarine":"#66cdaa","mediumblue":"#0000cd","mediumorchid":"#ba55d3","mediumpurple":"#9370d8","mediumseagreen":"#3cb371","mediumslateblue":"#7b68ee",
      "mediumspringgreen":"#00fa9a","mediumturquoise":"#48d1cc","mediumvioletred":"#c71585","midnightblue":"#191970","mintcream":"#f5fffa","mistyrose":"#ffe4e1","moccasin":"#ffe4b5",
      "navajowhite":"#ffdead","navy":"#000080",
      "oldlace":"#fdf5e6","olive":"#808000","olivedrab":"#6b8e23","orange":"#ffa500","orangered":"#ff4500","orchid":"#da70d6",
      "palegoldenrod":"#eee8aa","palegreen":"#98fb98","paleturquoise":"#afeeee","palevioletred":"#d87093","papayawhip":"#ffefd5","peachpuff":"#ffdab9","peru":"#cd853f","pink":"#ffc0cb","plum":"#dda0dd","powderblue":"#b0e0e6","purple":"#800080",
      "rebeccapurple":"#663399","red":"#ff0000","rosybrown":"#bc8f8f","royalblue":"#4169e1",
      "saddlebrown":"#8b4513","salmon":"#fa8072","sandybrown":"#f4a460","seagreen":"#2e8b57","seashell":"#fff5ee","sienna":"#a0522d","silver":"#c0c0c0","skyblue":"#87ceeb","slateblue":"#6a5acd","slategray":"#708090","snow":"#fffafa","springgreen":"#00ff7f","steelblue":"#4682b4",
      "tan":"#d2b48c","teal":"#008080","thistle":"#d8bfd8","tomato":"#ff6347","turquoise":"#40e0d0",
      "violet":"#ee82ee",
      "wheat":"#f5deb3","white":"#ffffff","whitesmoke":"#f5f5f5",
      "yellow":"#ffff00","yellowgreen":"#9acd32"};

      if (typeof colours[colour.toLowerCase()] !== 'undefined')
          return colours[colour.toLowerCase()];
      return colour;
    }

    /** ********************
     * AUX DISPLAY OBJECTS
     **********************/

    /**
     * Substitutes spaces by underscores in category names to avoid errors when
     * using these categories as html classes.
     *
     * @param {string} category
     * @return {string}
     */
    function cleanCategoryStr(category) {
      if (category == null || typeof category !== 'string') {
        return category;
      } else {
        return category.replace(/ /g, '_');
      }
    }

    /**
     * Appends Moebius Logo the the current display
     *
     */
    function appendMoebiusLogo() {
      const moebiusLogo = d3.select('#moebius_logo');
      const removed = moebiusLogo.remove();

      externalDiv.append(function() {
        return removed.node();
      })
          .attr('id', 'moebius-logo-' + graphSeed);
    }

    /**
     * Creates the search bar on the upper section of the display
     *
     * @return {input}
     */
    function createSearchBar() {
      const searchBar = externalDiv.append('input')
          .attr('placeholder', 'Search new node...')
          .attr('type', 'text')
          .attr('class', 'search-bar')
          .on('keypress', function(d) {
            if (d3.event.keyCode === 13) {
              const nodeID = d3.select(this).property('value');

              searchNewNode(nodeID);
              d3.select(this).property('value', '');
            }
          });
      return searchBar;
    }

    /**
     * Creates the menu button that contains: import graph, export graph,
     * filter graph and configuration.
     *
     * @return {div}
     */
    function createMenuButtons() {
      const menuButtons = externalDiv.append('div')
          .attr('class', 'menu-buttons');

      menuButtons.append('button').attr('type', 'button')
          .attr('class', 'open-menu-button')
          .append('svg')
          .attr('title', 'Filter menu')
          .attr('viewBox', '0 0 512 512')
          .attr('class', 'moebius-icon')
          .html(filterIcon)
          .on('click', function() {
            filterMenu.style('display', 'block');
          });

      menuButtons.append('button').attr('type', 'button')
          .attr('class', 'open-menu-button')
          .append('svg')
          .attr('title', 'Open menu')
          .attr('viewBox', '0 0 512 512')
          .attr('class', 'moebius-icon')
          .html(menuIcon)
          .on('click', function() {
            confMenu.style('display', 'block');
            updateConfigMenu(confMenu);
          });
      return menuButtons;
    }

    /** *******************
     * FILTER MENU
     **********************/

    /**
     * Creates a filter menu to hide nodes or links as a function of their
     * attributes
     *
     * @return {Object} The external div of the menu
     */
    function createFilterMenu() {
      const filterMenu = externalDiv.append('div')
          .attr('class', 'filter-box')
          .style('display', 'none');

      filterMenu.append('div').attr('class', 'box-title')
          .style('padding', '10px')
          .text('Filters');

      filterMenu.append('button').attr('type', 'button')
          .attr('class', 'close-menu-button')
          .append('svg')
          .attr('viewBox', '0 0 512 512')
          .attr('class', 'moebius-icon')
          .html(closeMenuIcon)
          .attr('title', 'Close Menu')
          .on('click', (d) => filterMenu.style('display', 'none'));

      const tabFilter = filterMenu.append('div')
          .attr('class', 'tab');

      tabFilter.append('button')
          .attr('class', 'tab-button')
          .attr('id', 'nodes-filter-tab-button')
          .text('Nodes')
          .classed('active', true)
          .on('click', function() {
            tabFilter.select('#nodes-filter-tab-button')
                .classed('active', true);

            tabFilter.select('#edges-filter-tab-button')
                .classed('active', false);

            externalDiv.select('.link-filter-container').style('display', 'none');
            externalDiv.select('.node-filter-container').style('display', 'block');
          });

      tabFilter.append('button')
          .attr('class', 'tab-button')
          .attr('id', 'edges-filter-tab-button')
          .text('Edges')
          .classed('active', false)
          .on('click', function() {
            tabFilter.select('#nodes-filter-tab-button')
                .classed('active', false);

            tabFilter.select('#edges-filter-tab-button')
                .classed('active', true);

            externalDiv.select('.link-filter-container').style('display', 'block');
            externalDiv.select('.node-filter-container').style('display', 'none');
          });

      updateFilterMenu(filterMenu);
      return filterMenu;
    }

    /**
     * Appends a toggle in a parentElement that will filter the given attribute
     * by its numeric values
     *
     * @param {Object} parentElement
     * @param {string} nodeOrLink
     * @param {string} attribute
     * @param {Object} attributeInfo
     * @return {Object}
     */
    function appendFilterToggle(parentElement, nodeOrLink, attribute, attributeInfo) {
      const labelToggle = parentElement.append('div').attr('class', 'toggle-container')
          .append('label')
          .attr('id', `toggle-${cleanCategoryStr(attribute)}`)
          .attr('class', 'switch');

      const toggleInput = labelToggle.append('input')
          .attr('type', 'checkbox')
          .on('change', function() {
            const isChecked = d3.select(`.${nodeOrLink}-filter-container-attribute-${cleanCategoryStr(attribute)}
                #toggle-${cleanCategoryStr(attribute)} input`).property('checked');
            // If the boxes are empty, we set selected items to null
            let selectedMin = '';
            let selectedMax = '';

            if (isChecked) {
              selectedMin = externalDiv
                  .select(`.${nodeOrLink}-filter-container-attribute-${cleanCategoryStr(attribute)}
                      .min-numeric-attribute-input input`).node().value;
              selectedMax = externalDiv
                  .select(`.${nodeOrLink}-filter-container-attribute-${cleanCategoryStr(attribute)}
                      .max-numeric-attribute-input input`).node().value;
            }

            filterAttribute(attribute, nodeOrLink, selectedMin, selectedMax, attributeInfo);
            updateHiddenNodesLinks();
          });

      labelToggle.append('span')
          .attr('class', 'toggle-slider round');
      return toggleInput;
    }

    /**
     * Given a div (parentElement) appends a button to activate or deactivate
     * the hideDisconnectedNodes function
     *
     * @param {Object} parentElement
     */
    function appendHideDisconnectedNodesToggle(parentElement) {
      const labelToggle = parentElement.append('div').attr('class', 'toggle-container')
          .append('label')
          .attr('id', 'toggle-hide-nodes')
          .attr('class', 'switch');

      labelToggle.append('input')
          .attr('type', 'checkbox')
          .on('change', function() {
            const isChecked = d3.select(this).property('checked');
            // console.log({isChecked});
            hideDisconnectedNodes(isChecked);
          });

      labelToggle.append('span')
          .attr('class', 'toggle-slider round');
    }

    /**
     * Function to execute when the numbers in the inputs boxes for a given
     * attribute change. It checks if the toggle if activated and if so, it
     * executes the 'change' callback to update filters
     *
     * @param {Object} toggleInput
     */
    function onChangeAttributeInput(toggleInput) {
      const thisFilterIsActive = toggleInput.property('checked');
      if (thisFilterIsActive) {
        toggleInput.property('checked', true);
        toggleInput.on('change')();
      }
    }

    /**
     * Retrieves the state of the filter menu. It is used to update
     * the filter menu when the graph changes (expand, collapse, etc)
     *
     * @param {Object} filterContainer
     * @return {Object}
     */
    function getActivatedFilters(filterContainer) {
      const activatedFilters = {};
      // For each attribute container we append its minValue, maxValue and if it is checked
      filterContainer.selectAll('.filter-container-attribute').each(function() {
        const thisAttribute = d3.select(this);

        const isChecked = thisAttribute.select('input').property('checked');
        const attributeName = thisAttribute.select('label').attr('id');
        const minValue = thisAttribute.select('.min-numeric-attribute-input input').node().value;
        const maxValue = thisAttribute.select('.max-numeric-attribute-input input').node().value;

        activatedFilters[attributeName] = {minValue, maxValue, isChecked};
      });
      return activatedFilters;
    }

    /**
     * Fills the legend with all the elements to filter all the numeric attributes
     *
     * @param {Object} filterMenu
     */
    function updateFilterMenu(filterMenu) {
      const isNodeSelected = filterMenu.select('#nodes-filter-tab-button').classed('active');
      // Since we're going to update the filter menu, we need to obtain
      // the previous containers. We first save its state and then we
      // remove them.
      const oldNodeFilterContainer = externalDiv.select('.node-filter-container');
      const oldLinkFilterContainer = externalDiv.select('.link-filter-container');

      // We need to retrieve the already activated filters in order to
      // activate them once the filter menu is updated
      const nodeActivatedFilters = getActivatedFilters(oldNodeFilterContainer);
      const linkActivatedFilters = getActivatedFilters(oldLinkFilterContainer);

      const isCheckHiddenNodes = getIfHiddenNodesToggleIsActivated();

      // We remove all the info that we already have
      oldNodeFilterContainer.remove();
      oldLinkFilterContainer.remove();

      // This object retrieves the information of which attributes are of the
      // type numeric and which are the min and max value founded.
      const nodesLinksFilterInfoNumber = {
        'node': computeFilterInfoNumber(graph.nodes),
        'link': computeFilterInfoNumber(graph.links),
      };

      // Creating an object with the new node and link filter containers
      const nodeLinksContainers = {
        'node': filterMenu.append('div').attr('class', 'node-filter-container'),
        'link': filterMenu.append('div').attr('class', 'link-filter-container')
            .style('display', 'none'),
      };

      const hideIndividualNodesDiv = nodeLinksContainers['node']
          .append('div')
          .attr('class', 'hide-individual-nodes-div');

      hideIndividualNodesDiv.append('h4')
          .text('Individual Node Filters');

      // Adding a button to hide selected nodes
      hideIndividualNodesDiv.append('div')
          .attr('class', 'moebius-button-wrapper')
          .append('button')
          .attr('class', 'moebius-button')
          .text('Hide Selected Nodes')
          .on('click', function() {
            const markedNodes = svgNodes.selectAll('.marked').data();
            changeStateHiddenIndividualNodes(markedNodes, true);
            updateHiddenNodesLinks();
          });

      hideIndividualNodesDiv.append('div')
          .attr('class', 'moebius-button-wrapper')
          .append('button')
          .attr('class', 'moebius-button')
          .text('Show Selected Nodes')
          .on('click', function() {
            const markedNodes = svgNodes.selectAll('.marked').data();
            changeStateHiddenIndividualNodes(markedNodes, false);
            updateHiddenNodesLinks();
          });

      hideIndividualNodesDiv.append('div')
          .attr('class', 'moebius-button-wrapper')
          .append('button')
          .attr('class', 'moebius-button')
          .text('Reset Individual Node Filters')
          .on('click', function() {
            svgNodes.selectAll('.node').classed('individual-node-hidden', false);
            updateHiddenNodesLinks();
          });

      // Adding a button to hide disconnected nodes
      const hideDisconnectedDiv = nodeLinksContainers['node'].append('div')
          .attr('class', 'hide-disconnected-nodes-div');

      // const titleDiv = hideDisconnectedDiv.append('div');
      // .attr('class', 'filter-container-attribute-name');

      hideDisconnectedDiv.append('text')
          .attr('class', 'hide-disconnected-node-name')
          .text('Hide disconnected nodes');

      appendHideDisconnectedNodesToggle(hideDisconnectedDiv);

      nodeLinksContainers['node'].append('div')
          .attr('class', 'hide-individual-nodes-div')
          .append('h4')
          .text('Node Attribute Filters');

      // appendFilterToggle(titleDiv, nodeOrLink, attribute, FilterInfoNumber);

      // We need to execute the on change function in the node-link-selector
      // toggle in order to hide one of the options, otherwise, all attributes
      // are visible
      // externalDiv.select('.node-link-selector input').on('change')();

      // We need to iterate over two things: the outer loop iterates over
      // node and link and the inner loop iterates over all the numeric
      // attributes that each one has.
      Object.entries(nodesLinksFilterInfoNumber).forEach(([nodeOrLink, FilterInfoNumber]) => {
        Object.entries(FilterInfoNumber).forEach(([attribute, values]) => {
          const filterContainer = nodeLinksContainers[nodeOrLink]
              .append('div')
              .attr('class', `filter-container-attribute
                  ${nodeOrLink}-filter-container-attribute-${cleanCategoryStr(attribute)}`);

          const titleDiv = filterContainer.append('div')
              .attr('class', 'filter-container-attribute-name');

          titleDiv.append('text')
              .attr('class', 'attribute-filter-name')
              .text(attribute);
          const toggleInput = appendFilterToggle(titleDiv, nodeOrLink, attribute, FilterInfoNumber);

          const inputsDiv = filterContainer.append('div')
              .attr('class', 'attribute-inputs-div');

          const minDiv = inputsDiv.append('div')
              .attr('class', 'min-numeric-attribute-input');

          const maxDiv = inputsDiv.append('div')
              .attr('class', 'max-numeric-attribute-input');

          minDiv.append('text')
              .text('Min: ' + values.min + ' ');

          minDiv.append('input')
              .style('width', '80px')
              .attr('type', 'number')
              // .attr('value', values.min)
              .on('change', (d) => onChangeAttributeInput(toggleInput));

          maxDiv.append('text')
              .text('Max: ' + values.max + ' ');

          maxDiv.append('input')
              .style('width', '80px')
              .attr('type', 'number')
              // .attr('value', values.max)
              .on('change', (d) => onChangeAttributeInput(toggleInput));
        });
      });

      // Once we have updated the filter menu, we need to activate the previously
      // activated filters
      Object.entries(nodeActivatedFilters).forEach(function([attributeName, values]) {
        const attributeToggleParent = nodeLinksContainers['node'].select(`#${cleanCategoryStr(attributeName)}`);
        const attributeFilter = d3.select(attributeToggleParent.node().parentNode.parentNode.parentNode);

        const minInput = attributeFilter.select('.min-numeric-attribute-input input');
        const maxInput = attributeFilter.select('.max-numeric-attribute-input input');
        minInput.property('value', values['minValue']);
        maxInput.property('value', values['maxValue']);

        if (values['isChecked']) {
          const attributeToggle = attributeToggleParent.select('input');
          attributeToggle.property('checked', true);
          attributeToggle.dispatch('change');
        }
      });

      Object.entries(linkActivatedFilters).forEach(function([attributeName, values]) {
        const attributeToggleParent = nodeLinksContainers['link'].select(`#${cleanCategoryStr(attributeName)}`);
        const attributeFilter = d3.select(attributeToggleParent.node().parentNode.parentNode.parentNode);

        const minInput = attributeFilter.select('.min-numeric-attribute-input input');
        const maxInput = attributeFilter.select('.max-numeric-attribute-input input');
        minInput.property('value', values['minValue']);
        maxInput.property('value', values['maxValue']);

        if (values['isChecked']) {
          const attributeToggle = attributeToggleParent.select('input');
          attributeToggle.property('checked', true);
          attributeToggle.dispatch('change');
        }
      });

      // If hidden nodes toggle is checked, we need to activate it again
      if (isCheckHiddenNodes) {
        const hiddenNodesToggle = externalDiv.select('#toggle-hide-nodes input');
        hiddenNodesToggle.property('checked', true);
        hiddenNodesToggle.dispatch('change');
      }

      if (!isNodeSelected) {
        filterMenu.select('#nodes-filter-tab-button').dispatch('click');
        filterMenu.select('#edges-filter-tab-button').dispatch('click');
      }
    }

    /**
     * Returns if the toggle of 'Hide disconnected nodes' is activated
     * @return {Boolean}
     */
    function getIfHiddenNodesToggleIsActivated() {
      const hiddenNodesToggle = externalDiv.select('#toggle-hide-nodes input');
      const isCheckHiddenNodes = (hiddenNodesToggle.empty()) ? false : hiddenNodesToggle.property('checked');
      return isCheckHiddenNodes;
    }

    /**
     * Returns an object with a list of numeric attributes. Each attribute contains
     * another object with a list of all the possible values, the min and the max
     * values of the attribute.
     *
     * @param {Array} elements
     * @return {Object}
     */
    function computeFilterInfoNumber(elements) {
      const attributes = {};
      // We iterate over all the attributes of all the graph and we pick all those
      // which are numeric
      elements.forEach((node) => {
        Object.entries(node).forEach(([attr, attrValue]) => {
          if (typeof attrValue !== 'number' || hiddenAttributes.includes(attr)) {
            return;
          }
          if (attrValue != null) {
            attributes[attr] = (!attributes.hasOwnProperty(attr)) ? [attrValue] : attributes[attr].concat(attrValue);
          }
        });
      });

      // Once we have computed all the possible values of each numeric attribute
      // we need to compute de min and max values for each one
      const attributesBoundariesTotal = {};
      Object.entries(attributes).forEach(([attr, attrValues]) => {
        const minValue = Math.min(...attrValues);
        const maxValue = Math.max(...attrValues);
        attributesBoundariesTotal[attr] = {
          'data': attrValues,
          'min': minValue,
          'max': maxValue,
        };
      });

      return attributesBoundariesTotal;
    }

    /**
     * Filters the given attribute with the minValue and maxValue given by the
     * user.
     *
     * @param {string} attribute
     * @param {string} nodeOrLink
     * @param {number} minValue
     * @param {number} maxValue
     * @param {number} numberAttributes
     */
    function filterAttribute(attribute, nodeOrLink, minValue, maxValue, numberAttributes) {
      // Update this function to support edges
      externalDiv.selectAll(`.${nodeOrLink}`).classed(`filtered-${cleanCategoryStr(attribute)}`, false);
      if (minValue == '' && maxValue == '') {
        return;
      }

      maxValue = (maxValue == '') ? numberAttributes[attribute]['max'] : maxValue;
      minValue = (minValue == '') ? numberAttributes[attribute]['min'] : minValue;

      const filteredNodesOrLinks = externalDiv.selectAll(`.${nodeOrLink}`).filter((nodeOrLink) => {
        if (nodeOrLink.hasOwnProperty(attribute) && nodeOrLink[attribute] != null) {
          if (nodeOrLink[attribute] < minValue || nodeOrLink[attribute] > maxValue) {
            return true;
          }
        }
        return false;
      });
      filteredNodesOrLinks.classed(`filtered-${cleanCategoryStr(attribute)}`, true);
    }

    /**
     * Checks which nodes or links have to be hidden as a function of the
     * filter classes that they have
     */
    function updateHiddenNodesLinks() {
      // First of all, we turn all the nodes and links to a visible state
      externalDiv.selectAll('.node').classed('hidden-node', false);
      externalDiv.selectAll('.link').classed('hidden-link', false);
      externalDiv.selectAll('.node').data().forEach((node) => {
        node._is_hidden = false;
      });

      // We will hide all those nodes that contains at least one 'filter'
      // class or a hidden-node-category class.
      const nodesToHide = externalDiv.selectAll('.node').filter(function() {
        const classes = [...this.classList];
        const containsFilteredClass = classes.some((cl) => cl.includes('filter') ||
          cl.includes('hidden-node-category') || cl.includes('individual-node-hidden'));

        return containsFilteredClass;
      });

      nodesToHide.classed('hidden-node', true);
      nodesToHide.data().forEach((node) => {
        node._is_hidden = true;
      });

      // We will hide all those links that contains at least one 'filter' class
      // or a hidden-link-category class or one of its adjacent nodes are hidden.
      const linksToHide = externalDiv.selectAll('.link').filter(function(link) {
        const isHiddenSource = link['source']['_is_hidden'];
        const isHiddenTarget = link['target']['_is_hidden'];

        const classes = [...this.classList];
        const containsFilteredClass = classes.some((cl) => {
          return cl.includes('filter') || cl.includes('hidden-link-category');
        });

        return isHiddenSource || isHiddenTarget || containsFilteredClass;
      });

      linksToHide.classed('hidden-link', true);

      // If hideUnconnectedNodes is set to true, we need to iterate over each
      // node to check whether it should be hide or not.
      const isCheckHiddenNodes = getIfHiddenNodesToggleIsActivated();

      if (isCheckHiddenNodes) hideDisconnectedNodes(isCheckHiddenNodes);
    }

    /**
       *
       * @param {Boolean} areHidden
       */
    function hideDisconnectedNodes(areHidden) {
      if (areHidden) {
        const unconnectedNodes = externalDiv.selectAll('.node').filter(function(node) {
          // First, we get the given node adjacent links and then we compute how
          // many are in total and how many are hidden.
          const adjacentLinks = externalDiv.selectAll('.link').filter(function(link) {
            return link.source.id === node.id || link.target.id === node.id;
          });

          const hiddenAdjacentLinks = adjacentLinks.filter(function(link) {
            // We check which links contains the class hidden-link
            const classes = [...this.classList];
            const linkIsFiltered = classes.some((cl) => {
              return cl.includes('hidden-link');
            });
            return linkIsFiltered;
          });

          // const nodeId = node.id;
          const totalAdjacentLinks = adjacentLinks.data().length;
          const totalHiddenAdjacentLinks = hiddenAdjacentLinks.data().length;
          const allLinksAreHidden = (totalAdjacentLinks - totalHiddenAdjacentLinks) === 0;

          // console.log({nodeId, totalAdjacentLinks, totalHiddenAdjacentLinks});

          if (totalAdjacentLinks > 0 && allLinksAreHidden) {
            return true;
          }
        });

        unconnectedNodes.classed('hidden-node', true);
      } else {
        updateHiddenNodesLinks();
      }
    }

    /**
     * Sets to true the class individual-node-hidden to all the given nodes
     *
     * @param {Array} markedNodes
     * @param {Boolean} state
     */
    function changeStateHiddenIndividualNodes(markedNodes, state) {
      const nodesIds = markedNodes.map((node) => node.id);
      const nodesToHide = externalDiv.selectAll('.node').filter(function(node) {
        return nodesIds.includes(node.id);
      });
      nodesToHide.classed('individual-node-hidden', state);
    }
  }

  /* ICONS */

  const saveIcon = `<g>
      <path d="M160.914,98.834l53.29-53.812v193.306c0,5.771,4.678,10.449,10.449,10.449s10.449-4.678,10.449-10.449V45.021
        l53.29,53.812c4.247,3.503,10.382,3.503,14.629,0c4.047-4.24,4.047-10.911,0-15.151l-71.053-71.576
        c-4.165-3.725-10.464-3.725-14.629,0l-71.053,71.576c-4.047,4.24-4.047,10.911,0,15.151
        C150.45,102.559,156.749,102.559,160.914,98.834z"/>
      <path d="M447.739,255.568l-59.037-127.478c-1.584-3.872-5.231-6.506-9.404-6.792h-50.155c-5.771,
      0-10.449,4.678-10.449,10.449
        s4.678,10.449,10.449,10.449h43.363l48.588,109.714h-59.559c-27.004-0.133-51.563,15.625-62.694,40.229
        c-8.062,16.923-25.141,27.698-43.886,27.69h-60.604c-18.745,0.008-35.823-10.767-43.886-27.69
        c-11.131-24.604-35.69-40.362-62.694-40.229H29.257l57.469-109.714h33.437c5.771,0,10.449-4.678,10.449-10.449
        s-4.678-10.449-10.449-10.449H80.457c-4.017,0.298-7.584,2.676-9.404,6.269L2.09,254.523c-1.139,
        1.53-1.859,3.331-2.09,5.224
        V390.36c0,28.735,25.078,49.633,53.812,49.633h341.682c28.735,0,53.812-20.898,53.812-49.633V259.748
        C449.018,258.278,448.488,256.866,447.739,255.568z M428.408,390.36c0,17.241-15.673,28.735-32.914,28.735H53.812
        c-17.241,0-32.914-11.494-32.914-28.735V272.809h66.873c18.745-0.008,35.823,10.767,43.886,27.69
        c11.131,24.604,35.69,40.362,62.694,40.229h60.604c27.004,0.133,51.563-15.625,62.694-40.229
        c8.062-16.923,25.141-27.698,43.886-27.69h66.873V390.36z"/>
    </g>`;

  const loadIcon = `<g>
      <path d="M447.739,251.298l-59.037-126.433c-1.731-3.54-5.484-5.625-9.404-5.224h-50.155c-5.771,0-10.449,
      4.678-10.449,10.449
        c0,5.771,4.678,10.449,10.449,10.449h43.363l48.588,104.49h-59.559c-27.004-0.133-51.563,15.625-62.694,40.229
        c-8.062,16.923-25.141,27.698-43.886,27.69h-60.604c-18.745,0.008-35.823-10.767-43.886-27.69
        c-11.131-24.604-35.69-40.362-62.694-40.229H29.257l57.469-104.49h33.437c5.771,0,10.449-4.678,10.449-10.449
        c0-5.771-4.678-10.449-10.449-10.449H80.457c-3.776-0.358-7.425,1.467-9.404,4.702L2.09,250.776
        c-1.209,1.072-1.958,2.569-2.09,4.18v130.09c0.832,29.282,24.524,52.744,53.812,53.29h341.682
        c29.289-0.546,52.98-24.008,53.812-53.29v-130.09C449.107,253.622,448.567,252.362,447.739,
        251.298z M428.408,385.045
        c-0.812,17.743-15.16,31.864-32.914,32.392H53.812c-17.754-0.528-32.102-14.648-32.914-32.392V265.927h66.873
        c18.745-0.008,35.823,10.767,43.886,27.69c11.131,24.604,35.69,40.362,62.694,40.229h60.604
        c27.004,0.133,51.563-15.625,62.694-40.229c8.062-16.923,25.141-27.698,43.886-27.69h66.873V385.045z"/>
      <path d="M217.339,252.865c3.706,4.04,9.986,4.31,14.025,0.603c0.21-0.192,0.411-0.394,0.603-0.603l71.053-71.576
        c3.462-4.617,2.527-11.166-2.09-14.629c-3.715-2.786-8.824-2.786-12.539,0l-53.29,53.29V21.42
        c0-5.771-4.678-10.449-10.449-10.449s-10.449,4.678-10.449,
        10.449v198.531l-53.29-53.29c-4.617-3.462-11.166-2.527-14.629,2.09
        c-2.786,3.715-2.786,8.824,0,12.539L217.339,252.865z"/>
    </g>`;

  const filterIcon = `<g>
      <path d="M204.356,198.311L307.278,55.16c3.795-4.529,4.611-10.852,
        2.09-16.196c-2.505-5.514-8.052-9.006-14.106-8.882H15.752
        C9.697,29.958,4.15,33.451,1.646,38.965C-1.021,44.21-0.41,50.524,3.213,55.16l101.355,143.151
        c2.897,4.703,4.351,10.153,4.18,15.674v161.437c0.179,5.416,3.142,10.355,7.837,13.061c2.761,
        1.884,6.067,2.803,9.404,2.612
        c2.144,0.173,4.297-0.186,6.269-1.045l56.424-21.943c5.837-2.119,9.493-7.927,8.882-14.106V213.985
        C198.12,208.175,200.497,202.69,204.356,198.311z M187.115,185.773c-6.201,8.161-9.838,17.981-10.449,28.212v135.837
        l-47.02,18.286V213.985c0.465-9.915-2.486-19.689-8.359-27.69L25.678,50.981h259.657L187.115,185.773z"/>
      <path d="M327.654,197.789c-54.822-0.288-99.497,43.921-99.785,98.743c-0.288,54.822,43.921,99.497,98.743,99.785
        s99.497-43.921,99.785-98.743c0.002-0.347,0.002-0.695,0-1.042C426.397,241.998,382.188,197.789,327.654,197.789z
        M327.654,374.899c-43.28,0.289-78.599-34.563-78.888-77.843c-0.289-43.28,34.563-78.6,77.843-78.888
        c43.28-0.289,78.599,34.563,78.888,77.843c0.001,0.174,0.002,0.347,0.002,0.521C405.5,339.61,370.731,
        374.612,327.654,374.899z"
        />
      <path d="M357.956,286.083h-19.331v-18.808c0-5.771-4.678-10.449-10.449-10.449s-10.449,4.678-10.449,
        10.449v18.808h-20.376
        c-5.771,0-10.449,4.678-10.449,10.449c0,5.771,4.678,10.449,10.449,10.449h20.376v20.375c0,5.771,
        4.678,10.449,10.449,10.449
        s10.449-4.678,10.449-10.449v-20.375h19.331c5.771,0,10.449-4.678,10.449-10.449
        C368.405,290.761,363.727,286.083,357.956,286.083z"/>
    </g>`;

  const menuIcon = `<g>
      <path d="M410.144,246.617h0.522c4.788-1.045,7.972-5.592,7.314-10.449v-53.812c0.657-4.857-2.526-9.404-7.314-10.449
        l-32.914-5.747c-4.087-15.883-10.235-31.164-18.286-45.453l19.853-27.69c2.5-4.307,
        2.085-9.71-1.045-13.584l-38.661-38.661
        c-3.737-3.458-9.362-3.891-13.584-1.045L298.34,59.58c-14.352-7.92-29.615-14.06-45.453-18.286L247.139,8.38
        c-0.548-4.989-4.917-8.668-9.927-8.359h-54.335c-5.12-0.333-9.65,3.291-10.449,8.359l-5.747,32.914
        c-15.901,4.275-31.18,10.597-45.453,18.808L93.54,40.25c-4.307-2.5-9.71-2.085-13.584,1.045L41.295,79.956
        c-3.458,3.737-3.891,9.362-1.045,13.584l19.853,27.69c-8.299,14.229-14.627,29.52-18.808,45.453L8.38,172.429
        c-5.068,0.799-8.692,5.329-8.359,10.449v54.335c-0.309,5.009,3.37,9.378,8.359,9.927l32.914,5.747
        c4.275,15.901,10.597,31.18,18.808,45.453l-19.853,27.69c-2.5,4.307-2.085,9.71,1.045,13.584l38.661,38.661
        c3.737,3.458,9.362,3.891,13.584,1.045l27.69-19.853c14.229,8.299,29.52,14.627,45.453,18.808l5.747,32.392
        c1.045,4.788,5.592,7.972,10.449,7.314h54.335c4.669,0.374,8.901-2.744,9.927-7.314c18.751,11.894,40.488,
        18.234,62.694,18.286
        c65.787,0,119.118-53.331,119.118-119.118C428.993,287.377,422.454,265.399,410.144,246.617z M228.331,
        397.082h-37.094
        l-5.224-30.302c-0.462-4.122-3.715-7.375-7.837-7.837c-18.298-3.991-35.787-11.058-51.722-20.898
        c-3.591-2.141-8.112-1.935-11.494,0.522l-26.122,18.286l-26.122-26.122l18.286-26.122c2.296-3.487,
        2.296-8.007,0-11.494
        c-9.796-15.958-16.859-33.439-20.898-51.722c-0.632-4.037-3.799-7.205-7.837-7.837l-31.347-5.224
        v-37.094l31.347-5.224
        c4.122-0.462,7.375-3.715,7.837-7.837c4.223-18.226,11.275-35.678,20.898-51.722c2.614-3.385,2.614-8.108,
        0-11.494L62.715,88.838
        l26.122-26.122l26.122,18.286c3.487,2.297,8.007,2.297,11.494,0c15.958-9.796,33.439-16.859,51.722-20.898
        c4.038-0.632,7.205-3.799,7.837-7.837l5.224-31.347h37.094l5.224,31.347c0.462,4.122,3.715,7.375,7.837,7.837
        c18.226,4.223,35.678,11.275,51.722,20.898c3.385,2.614,8.108,2.614,11.494,
        0l26.122-18.808l26.122,26.122l-18.286,26.122
        c-2.297,3.487-2.297,8.007,0,11.494c9.796,15.958,16.859,33.439,20.898,51.722c1.045,4.18,3.135,7.314,7.314,
        7.837l30.302,5.224
        v37.094h-2.09c-22.049-23.961-53.119-37.602-85.682-37.616h-3.657c-9.38-45.706-49.473-78.608-96.131-78.89
        c-53.957,0-97.698,43.741-97.698,97.698c-0.5,47.117,33.048,87.728,
        79.412,96.131c-0.428,1.529-0.605,3.117-0.522,4.702
        c-0.05,32.576,13.601,63.671,37.616,85.682V397.082z M285.278,193.327c-45.465,10.12-81.048,45.5-91.429,90.906
        c-41.55-8.524-68.323-49.118-59.798-90.668c7.347-35.81,38.916-61.478,75.472-61.365
        C245.971,132.329,277.451,157.73,285.278,193.327z M309.833,408.054c-54.246,0-98.22-43.975-98.22-98.22
        c0-54.246,43.975-98.22,98.22-98.22s98.22,43.975,98.22,98.22S364.079,408.054,309.833,408.054z"/>
      <path d="M365.735,303.042H323.94v-41.796c0-5.771-4.678-10.449-10.449-10.449s-10.449,4.678-10.449,
        10.449v41.796h-41.796
        c-5.771,0-10.449,4.678-10.449,10.449s4.678,10.449,10.449,10.449h41.796v41.796c0,5.771,4.678,10.449,10.449,10.449
        s10.449-4.678,10.449-10.449V323.94h41.796c5.771,0,10.449-4.678,10.449-10.449S371.506,303.042,365.735,303.042z"/>
    </g>`;

  const expandIcon = `<g>
      <path d="M128,32V0H16C7.163,0,0,7.163,0,16v112h32V54.56L180.64,203.2l22.56-22.56L54.56,32H128z"/>
      <path d="M496,0H384v32h73.44L308.8,180.64l22.56,22.56L480,54.56V128h32V16C512,7.163,504.837,0,496,0z"/>
      <path d="M480,457.44L331.36,308.8l-22.56,22.56L457.44,480H384v32h112c8.837,0,16-7.163,16-16V384h-32V457.44z"/>
      <path d="M180.64,308.64L32,457.44V384H0v112c0,8.837,7.163,16,16,16h112v-32H54.56L203.2,331.36L180.64,308.64z"/>
    </g>`;

  const collapseIcon = `<g>
      <path d="M171.36,148.8L22.72,0L0,22.72l148.8,148.64H75.36v32h112c8.837,0,16-7.163,16-16v-112h-32V148.8z"/>
      <path d="M315.36,203.36h112v-32h-73.44L502.56,22.72L480,0L331.36,148.8V75.36h-32v112
        C299.36,196.197,306.523,203.36,315.36,203.36z"/>
      <path d="M427.36,331.36v-32h-112c-8.837,0-16,7.163-16,16v112h32v-73.44L480,502.56L502.56,480L353.92,
               331.36H427.36z"/>
      <path d="M187.36,299.36h-112v32h73.44L0,480l22.56,22.56l148.8-148.64v73.44h32v-112
        C203.36,306.523,196.197,299.36,187.36,299.36z"/>
    </g>`;

  const resetLegendIcon = `<g>
      <path d="M231.298,17.068c-57.746-0.156-113.278,22.209-154.797,62.343V17.067C76.501,7.641,68.86,0,59.434,0
        S42.368,7.641,42.368,17.067v102.4c-0.002,7.349,4.701,13.874,11.674,16.196l102.4,34.133c8.954,2.979,18.628-1.866,
        21.606-10.82
        c2.979-8.954-1.866-18.628-10.82-21.606l-75.605-25.156c69.841-76.055,188.114-81.093,264.169-11.252
        s81.093,188.114,11.252,264.169s-188.114,81.093-264.169,11.252c-46.628-42.818-68.422-106.323-57.912-168.75
        c1.653-9.28-4.529-18.142-13.808-19.796s-18.142,4.529-19.796,13.808c-0.018,0.101-0.035,0.203-0.051,0.304
        c-2.043,12.222-3.071,24.592-3.072,36.983C8.375,361.408,107.626,460.659,230.101,460.8
        c122.533,0.331,222.134-98.734,222.465-221.267C452.896,117,353.832,17.399,231.298,17.068z"/>
    </g>`;

  const closeMenuIcon = `<g>
      <path d="M284.286,256.002L506.143,34.144c7.811-7.811,7.811-20.475,0-28.285c-7.811-7.81-20.475-7.811-28.285,
        0L256,227.717L34.143,5.859c-7.811-7.811-20.475-7.811-28.285,0c-7.81,7.811-7.811,20.475,0,28.285l221.857,
        221.857L5.858,477.859c-7.811,7.811-7.811,20.475,0,28.285c3.905,3.905,9.024,5.857,14.143,5.857c5.119,0,
        10.237-1.952,14.143-5.857L256,284.287l221.857,221.857c3.905,3.905,9.024,5.857,14.143,5.857s10.237-1.952,
        14.143-5.857c7.811-7.811,7.811-20.475,0-28.285L284.286,256.002z"/>
    </g>`;

  return draw;
});
