const PIPELINE_STEPS = [
  ["plan", "Plan"],
  ["retrieve", "Literature retrieval"],
  ["extract", "Entity extraction"],
  ["build_kg", "Knowledge graph"],
  ["score_evidence", "Evidence scoring"],
  ["rank_targets", "Target ranking"],
  ["triage_molecules", "Molecule triage"],
  ["write_report", "Report writing"],
  ["verify_citations", "Citation check"],
];

const PROJECT_LAYERS = [
  {
    title: "Retrieval",
    detail: "PubMed, Europe PMC, OpenAlex, PubTator3, caching, dedupe.",
    chips: ["PubMed", "Europe PMC", "OpenAlex", "PubTator3"],
  },
  {
    title: "Extraction",
    detail: "PubTator3 BioC entities and typed relations with measured fallback.",
    chips: ["PubTator3", "scispaCy", "local LLM"],
  },
  {
    title: "Grounding",
    detail: "Reference ontology IDs for genes, disease, chemicals, variants.",
    chips: ["NCBI Gene", "MeSH", "ChEBI", "dbSNP", "EFO"],
  },
  {
    title: "Knowledge graph",
    detail: "Neo4j property graph with provenance and GDS centrality.",
    chips: ["Neo4j", "APOC", "PageRank", "Degree", "Betweenness"],
  },
  {
    title: "Evidence",
    detail: "Open Targets scoring and robust, plausible, speculative tiers.",
    chips: ["Open Targets", "harmonic scoring", "tractability"],
  },
  {
    title: "Ranking",
    detail: "Transparent weighted target score with visible components.",
    chips: ["centrality", "association", "druggability", "genetics", "novelty"],
  },
  {
    title: "Molecules",
    detail: "Known ChEMBL actives only, scoped for research triage.",
    chips: ["ChEMBL", "RDKit", "known actives"],
  },
  {
    title: "Reports",
    detail: "Markdown, HTML, PDF, JSON, and retrieved-only citation checks.",
    chips: ["SSE", "PDF", "JSON", "citations"],
  },
];

const form = document.querySelector("#search-form");
const diseaseInput = document.querySelector("#disease-input");
const runButton = document.querySelector("#run-button");
const steps = document.querySelector("#steps");
const jobStatus = document.querySelector("#job-status");
const pipelineSubtitle = document.querySelector("#pipeline-subtitle");
const resultSubtitle = document.querySelector("#result-subtitle");
const resultCount = document.querySelector("#result-count");
const citationAccuracy = document.querySelector("#citation-accuracy");
const topTarget = document.querySelector("#top-target");
const kgSize = document.querySelector("#kg-size");
const extractionMetric = document.querySelector("#extraction-metric");
const targetsBody = document.querySelector("#targets-body");
const targetDetail = document.querySelector("#target-detail");
const systemStatus = document.querySelector("#system-status");
const evidenceList = document.querySelector("#evidence-list");
const kgMetrics = document.querySelector("#kg-metrics");
const coverageMap = document.querySelector("#coverage-map");
const moleculeList = document.querySelector("#molecule-list");
const citationList = document.querySelector("#citation-list");
const serviceGrid = document.querySelector("#service-grid");
const graphCanvas = document.querySelector("#kg-graph");
const graphCount = document.querySelector("#graph-count");
const graphLegend = document.querySelector("#graph-legend");
const graphEdgeList = document.querySelector("#graph-edge-list");
const reportLinks = {
  json: document.querySelector("#report-json"),
  markdown: document.querySelector("#report-md"),
  pdf: document.querySelector("#report-pdf"),
};

let selectedTargetId = null;
let currentHealth = null;
let currentReport = null;

function setText(node, value) {
  node.textContent = value;
}

function asPercent(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  return `${Math.round(value * 100)}%`;
}

function asFixed(value, digits = 2) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "--";
  }
  return value.toFixed(digits);
}

function normalizeLabel(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function clearNode(node) {
  node.replaceChildren();
}

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function renderSteps(doneSteps = []) {
  const done = new Set(doneSteps);
  steps.replaceChildren(
    ...PIPELINE_STEPS.map(([id, label], index) => {
      const item = make("li");
      if (done.has(id)) {
        item.classList.add("done");
      }
      const marker = make("span", "step-marker", done.has(id) ? "OK" : String(index + 1));
      const text = make("span", "", label);
      item.append(marker, text);
      return item;
    }),
  );
}

function setReportLinks(jobId) {
  const formats = {
    json: "json",
    markdown: "markdown",
    pdf: "pdf",
  };
  Object.entries(reportLinks).forEach(([key, link]) => {
    link.href = `/jobs/${jobId}/result?format=${formats[key]}`;
    link.classList.remove("disabled");
  });
}

function clearReportLinks() {
  Object.values(reportLinks).forEach((link) => {
    link.href = "#";
    link.classList.add("disabled");
  });
}

function scoreCell(value) {
  const safe = typeof value === "number" ? value : 0;
  const wrapper = make("div", "score-bar");
  const label = make("span", "", asFixed(value, 2));
  const track = make("span", "bar-track");
  const fill = make("span", "bar-fill");
  fill.style.width = asPercent(safe);
  track.append(fill);
  wrapper.append(label, track);
  return wrapper;
}

function tierBadge(tier) {
  const safeTier = String(tier || "unknown").toLowerCase();
  const badge = make("span", `tier ${safeTier}`, safeTier);
  return badge;
}

function citationNode(citation) {
  const text = citation || "none";
  const match = String(text).match(/PMID:(\d+)/);
  if (!match) {
    return make("span", "", text);
  }
  const link = make("a", "citation-link", text);
  link.href = `https://pubmed.ncbi.nlm.nih.gov/${match[1]}/`;
  link.target = "_blank";
  link.rel = "noreferrer";
  return link;
}

function keyValueRow(label, value) {
  const row = make("div", "key-value-row");
  row.append(make("span", "", label), make("span", "", value));
  return row;
}

function metricBox(label, value) {
  const box = make("div", "metric-box");
  box.append(make("span", "", label), make("strong", "", value));
  return box;
}

function chips(values) {
  const list = make("ul", "chip-list");
  values.forEach((value) => list.append(make("li", "chip", value)));
  return list;
}

function renderCoverageMap() {
  clearNode(coverageMap);
  PROJECT_LAYERS.forEach((layer) => {
    const item = make("div", "coverage-item");
    item.append(make("h3", "", layer.title), make("p", "", layer.detail), chips(layer.chips));
    coverageMap.append(item);
  });
}

function resetSummary() {
  setText(jobStatus, "idle");
  setText(topTarget, "--");
  setText(citationAccuracy, "--");
  setText(kgSize, "--");
  setText(extractionMetric, "--");
  setText(resultCount, "0 targets");
}

function renderSummary(report) {
  const targets = report.targets || [];
  setText(jobStatus, "succeeded");
  setText(topTarget, targets[0]?.target_symbol || "--");
  setText(citationAccuracy, asPercent(report.citation_accuracy));
  setText(
    kgSize,
    report.kg_nodes || report.kg_relations
      ? `${report.kg_nodes || 0} nodes / ${report.kg_relations || 0} edges`
      : "--",
  );
  const precision = report.extraction_precision_vs_pubtator3;
  const recall = report.extraction_recall_vs_pubtator3;
  setText(
    extractionMetric,
    typeof precision === "number" || typeof recall === "number"
      ? `${asFixed(precision, 3)} / ${asFixed(recall, 3)}`
      : "--",
  );
  setText(resultCount, `${targets.length} targets`);
}

function renderTargets(report) {
  const targets = report.targets || [];
  if (targets.length === 0) {
    targetsBody.innerHTML =
      '<tr><td colspan="7" class="empty-cell">No targets were returned for this run.</td></tr>';
    targetDetail.className = "target-detail empty-detail";
    targetDetail.textContent = "Select a ranked target.";
    return;
  }

  targetsBody.replaceChildren(
    ...targets.map((target) => {
      const row = make("tr");
      row.dataset.targetId = target.target_id;
      if (target.target_id === selectedTargetId) {
        row.classList.add("selected");
      }
      row.addEventListener("click", () => {
        selectedTargetId = target.target_id;
        renderTargets(report);
        renderDetail(target, report);
      });

      const rank = make("td", "", target.rank);
      const targetCell = make("td");
      targetCell.append(
        make("span", "target-symbol", target.target_symbol),
        make("span", "target-id", target.target_id),
      );
      const tier = make("td");
      tier.append(tierBadge(target.evidence_tier));
      const score = make("td");
      score.append(scoreCell(target.composite_score));
      const genetic = make("td", "", asPercent(target.component_breakdown?.genetic_evidence));
      const druggability = make(
        "td",
        "",
        asPercent(target.component_breakdown?.druggability),
      );
      const citation = make("td");
      citation.append(citationNode(target.citation));

      row.append(rank, targetCell, tier, score, genetic, druggability, citation);
      return row;
    }),
  );

  const selected =
    targets.find((target) => target.target_id === selectedTargetId) || targets[0];
  selectedTargetId = selected.target_id;
  renderDetail(selected, report);
}

function moleculeItemsForTarget(report, targetId) {
  const triage = report.triaged_molecules || {};
  const items = triage[targetId];
  return Array.isArray(items) ? items : [];
}

function renderDetail(target, report) {
  targetDetail.className = "target-detail";
  clearNode(targetDetail);

  const title = make("div", "detail-title");
  title.append(make("strong", "", target.target_symbol), make("span", "", target.target_id));
  targetDetail.append(title, tierBadge(target.evidence_tier));

  const components = make("div", "component-list");
  Object.entries(target.component_breakdown || {}).forEach(([name, value]) => {
    components.append(
      keyValueRow(normalizeLabel(name), typeof value === "number" ? value.toFixed(2) : value),
    );
  });
  targetDetail.append(components);

  const citationBlock = make("div", "detail-block");
  citationBlock.append(make("h3", "", "Citation"));
  const citation = make("div");
  citation.append(citationNode(target.citation));
  citationBlock.append(citation);
  targetDetail.append(citationBlock);

  const moleculeBlock = make("div", "detail-block");
  moleculeBlock.append(make("h3", "", "Known molecule triage"));
  const targetMolecules = moleculeItemsForTarget(report, target.target_id);
  if (targetMolecules.length === 0) {
    moleculeBlock.append(make("p", "", "No known active molecule triage returned for this target."));
  } else {
    targetMolecules.forEach((molecule) => {
      const item = make("p");
      item.textContent = `${molecule.molecule_chembl_id || "molecule"} - ${
        molecule.scope_label || "known actives only"
      }`;
      moleculeBlock.append(item);
    });
  }
  targetDetail.append(moleculeBlock);

  const validationBlock = make("div", "detail-block");
  validationBlock.append(make("h3", "", "Validation experiments"));
  validationBlock.append(chips(report.validation_experiments || []));
  targetDetail.append(validationBlock);
}

function renderEvidence(report) {
  clearNode(evidenceList);
  evidenceList.append(
    keyValueRow("Evidence scored", report.evidence_scored ? "yes" : "not reported"),
    keyValueRow("Citation gate", asPercent(report.citation_accuracy)),
    keyValueRow("Scope", report.scope || "research-only"),
    keyValueRow("Rejected citations", String((report.rejected_citations || []).length)),
    keyValueRow("Degraded steps", String((report.errors || []).length)),
  );
}

function renderKgAndExtraction(report) {
  clearNode(kgMetrics);
  kgMetrics.append(
    metricBox("KG nodes", String(report.kg_nodes ?? "--")),
    metricBox("KG relations", String(report.kg_relations ?? "--")),
    metricBox("Retrieved PMIDs", String((report.retrieved_pmids || []).length)),
    metricBox("Verified citations", String((report.verified_citations || []).length)),
    metricBox("NER precision", asFixed(report.extraction_precision_vs_pubtator3, 3)),
    metricBox("NER recall", asFixed(report.extraction_recall_vs_pubtator3, 3)),
  );
}

function renderMolecules(report) {
  clearNode(moleculeList);
  moleculeList.classList.remove("empty-detail");
  const triage = report.triaged_molecules || {};
  const targetById = new Map((report.targets || []).map((target) => [target.target_id, target]));
  const entries = Object.entries(triage).filter(([, molecules]) => Array.isArray(molecules));

  if (entries.length === 0) {
    moleculeList.classList.add("empty-detail");
    moleculeList.textContent = "No molecule triage entries were returned for this run.";
    return;
  }

  entries.forEach(([targetId, molecules]) => {
    const target = targetById.get(targetId);
    const item = make("div", "molecule-item");
    item.append(
      make("h3", "", target ? `${target.target_symbol} (${targetId})` : targetId),
      chips(molecules.map((molecule) => molecule.molecule_chembl_id || "molecule")),
    );
    molecules.forEach((molecule) => {
      const detail = make("p");
      const qed =
        typeof molecule.qed === "number" ? `; QED ${molecule.qed.toFixed(2)}` : "";
      detail.textContent = `${molecule.scope_label || "known actives only"}${qed}`;
      item.append(detail);
    });
    moleculeList.append(item);
  });
}

function renderCitations(report) {
  clearNode(citationList);
  citationList.classList.remove("empty-detail");
  const details = report.citation_details || [];
  const pmids = report.retrieved_pmids || [];

  if (details.length === 0 && pmids.length === 0) {
    citationList.classList.add("empty-detail");
    citationList.textContent = "No verified citations yet.";
    return;
  }

  if (details.length > 0) {
    details.forEach((detail) => {
      const item = make("div", "citation-item");
      const title = make("p");
      title.append(citationNode(detail.identifier));
      const status = detail.verified ? "verified in retrieved evidence" : "not verified";
      item.append(title, make("p", "", status));
      citationList.append(item);
    });
    return;
  }

  pmids.forEach((pmid) => {
    const item = make("div", "citation-item");
    const title = make("p");
    title.append(citationNode(`PMID:${pmid}`));
    item.append(title);
    citationList.append(item);
  });
}

const GRAPH_WIDTH = 920;
const GRAPH_HEIGHT = 520;
const SVG_NS = "http://www.w3.org/2000/svg";
const GRAPH_TYPE_ORDER = [
  "disease",
  "gene",
  "pathway",
  "phenotype",
  "variant",
  "compound",
  "chemical",
  "publication",
];
const GRAPH_TYPE_X = {
  disease: 120,
  gene: 360,
  pathway: 520,
  phenotype: 520,
  variant: 520,
  compound: 610,
  chemical: 610,
  publication: 790,
  other: 500,
};

function svgElement(tag, attributes = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attributes).forEach(([key, value]) => {
    node.setAttribute(key, String(value));
  });
  return node;
}

function graphTypeClass(type) {
  return String(type || "other").toLowerCase().replace(/[^a-z0-9-]/g, "-");
}

function truncateLabel(value, maxLength = 22) {
  const text = String(value || "");
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength - 1)}...`;
}

function groupGraphNodes(nodes) {
  const groups = new Map();
  nodes.forEach((node) => {
    const type = GRAPH_TYPE_ORDER.includes(node.type) ? node.type : "other";
    if (!groups.has(type)) {
      groups.set(type, []);
    }
    groups.get(type).push(node);
  });
  return groups;
}

function graphLayout(nodes) {
  const positions = new Map();
  const groups = groupGraphNodes(nodes);
  const orderedGroups = [
    ...GRAPH_TYPE_ORDER.filter((type) => groups.has(type)),
    ...[...groups.keys()].filter((type) => !GRAPH_TYPE_ORDER.includes(type)),
  ];

  orderedGroups.forEach((type) => {
    const group = groups.get(type);
    const x = GRAPH_TYPE_X[type] || GRAPH_TYPE_X.other;
    const yGap = GRAPH_HEIGHT / (group.length + 1);
    group.forEach((node, index) => {
      positions.set(node.id, {
        x,
        y: Math.max(58, Math.min(GRAPH_HEIGHT - 58, yGap * (index + 1))),
      });
    });
  });

  return positions;
}

function graphNodeRadius(type) {
  if (type === "disease") {
    return 31;
  }
  if (type === "gene") {
    return 24;
  }
  if (type === "publication") {
    return 20;
  }
  return 22;
}

function addGraphMarkers(svg) {
  const defs = svgElement("defs");
  const marker = svgElement("marker", {
    id: "kg-arrow",
    viewBox: "0 0 10 10",
    refX: 9,
    refY: 5,
    markerWidth: 6,
    markerHeight: 6,
    orient: "auto-start-reverse",
  });
  marker.append(svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z" }));
  defs.append(marker);
  svg.append(defs);
}

function renderGraphLegend(nodes) {
  clearNode(graphLegend);
  const types = [...new Set(nodes.map((node) => node.type || "other"))];
  if (types.length === 0) {
    graphLegend.textContent = "No graph nodes yet.";
    return;
  }
  types.forEach((type) => {
    const item = make("div", "legend-item");
    item.append(make("span", `legend-dot ${graphTypeClass(type)}`));
    item.append(make("span", "", normalizeLabel(type)));
    graphLegend.append(item);
  });
}

function renderGraphEdgesList(graph, nodeById) {
  clearNode(graphEdgeList);
  graphEdgeList.className = "graph-edge-list";
  const edges = graph.edges || [];
  if (edges.length === 0) {
    graphEdgeList.classList.add("empty-detail");
    graphEdgeList.textContent = "Run a target discovery job to render graph edges.";
    return;
  }
  edges.slice(0, 16).forEach((edge) => {
    const item = make("div", "edge-item");
    const source = nodeById.get(edge.source)?.label || edge.source;
    const target = nodeById.get(edge.target)?.label || edge.target;
    const title = make(
      "strong",
      "",
      `${truncateLabel(source, 18)} ${edge.relation} ${truncateLabel(target, 18)}`,
    );
    const pmids = (edge.source_pmids || []).filter(Boolean).join(", ");
    const detail = make(
      "span",
      "",
      `${edge.source_db || "source"}${pmids ? `; PMID ${pmids}` : ""}`,
    );
    item.append(title, detail);
    graphEdgeList.append(item);
  });
}

function renderKnowledgeGraph(report) {
  const graph = report?.knowledge_graph || { nodes: [], edges: [] };
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const targetById = new Map((report?.targets || []).map((target) => [target.target_id, target]));
  const positions = graphLayout(nodes);

  clearNode(graphCanvas);
  addGraphMarkers(graphCanvas);
  setText(graphCount, `${nodes.length} nodes / ${edges.length} edges`);

  if (nodes.length === 0) {
    const empty = svgElement("text", {
      x: GRAPH_WIDTH / 2,
      y: GRAPH_HEIGHT / 2,
      class: "graph-empty-text",
      "text-anchor": "middle",
    });
    empty.textContent = "Run a disease query to render the knowledge graph.";
    graphCanvas.append(empty);
    renderGraphLegend(nodes);
    renderGraphEdgesList(graph, nodeById);
    return;
  }

  const edgeLayer = svgElement("g", { class: "edge-layer" });
  edges.forEach((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) {
      return;
    }
    const line = svgElement("line", {
      x1: source.x,
      y1: source.y,
      x2: target.x,
      y2: target.y,
      class: `graph-edge ${graphTypeClass(edge.relation)}`,
      "marker-end": "url(#kg-arrow)",
    });
    edgeLayer.append(line);
    const label = svgElement("text", {
      x: (source.x + target.x) / 2,
      y: (source.y + target.y) / 2 - 6,
      class: "edge-label",
      "text-anchor": "middle",
    });
    label.textContent = truncateLabel(edge.relation, 18);
    edgeLayer.append(label);
  });
  graphCanvas.append(edgeLayer);

  const nodeLayer = svgElement("g", { class: "node-layer" });
  nodes.forEach((node) => {
    const position = positions.get(node.id);
    if (!position) {
      return;
    }
    const group = svgElement("g", {
      class: `graph-node ${graphTypeClass(node.type)} ${
        node.id === selectedTargetId ? "selected" : ""
      }`,
      tabindex: "0",
    });
    const circle = svgElement("circle", {
      cx: position.x,
      cy: position.y,
      r: graphNodeRadius(node.type),
    });
    const label = svgElement("text", {
      x: position.x,
      y: position.y + graphNodeRadius(node.type) + 18,
      "text-anchor": "middle",
    });
    label.textContent = truncateLabel(node.label, node.type === "disease" ? 18 : 16);
    const title = svgElement("title");
    title.textContent = `${node.label} (${node.type})`;
    group.append(title, circle, label);
    if (targetById.has(node.id)) {
      group.classList.add("clickable");
      group.addEventListener("click", () => {
        selectedTargetId = node.id;
        renderTargets(currentReport);
        renderKnowledgeGraph(currentReport);
      });
    }
    nodeLayer.append(group);
  });
  graphCanvas.append(nodeLayer);
  renderGraphLegend(nodes);
  renderGraphEdgesList(graph, nodeById);
}

function renderServices(payload) {
  currentHealth = payload;
  clearNode(serviceGrid);
  const components = payload?.components || {
    api: { ok: false },
    neo4j: { ok: false },
    ollama: { ok: false },
    redis: { ok: true, url: "redis://redis:6379/0" },
  };
  if (!components.redis) {
    components.redis = { ok: true, url: "redis://redis:6379/0" };
  }

  Object.entries(components).forEach(([name, info]) => {
    const item = make("div", `service-item ${info.ok ? "ok" : "bad"}`);
    item.append(
      make("div", "service-name", normalizeLabel(name)),
      make("p", "", info.uri || info.url || info.error || (info.ok ? "available" : "unavailable")),
    );
    serviceGrid.append(item);
  });
}

function renderResult(jobId, report) {
  currentReport = report;
  renderSummary(report);
  renderTargets(report);
  renderKnowledgeGraph(report);
  renderEvidence(report);
  renderKgAndExtraction(report);
  renderMolecules(report);
  renderCitations(report);
  setReportLinks(jobId);
  setText(
    resultSubtitle,
    `Results for ${report.disease_query || "selected disease"}.`,
  );
  setText(pipelineSubtitle, "All pipeline stages completed.");
}

function setRunning(disease) {
  runButton.disabled = true;
  runButton.textContent = "Running";
  selectedTargetId = null;
  currentReport = null;
  clearReportLinks();
  renderSteps([]);
  renderKnowledgeGraph(null);
  resetSummary();
  setText(jobStatus, "running");
  setText(pipelineSubtitle, "Streaming progress from the local FastAPI job.");
  setText(resultSubtitle, `Running target discovery for ${disease}.`);
  targetsBody.innerHTML =
    '<tr><td colspan="7" class="empty-cell">Pipeline is running.</td></tr>';
  targetDetail.className = "target-detail empty-detail";
  targetDetail.textContent = "Waiting for ranked targets.";
  moleculeList.className = "molecule-list empty-detail";
  moleculeList.textContent = "Waiting for molecule triage.";
  citationList.className = "citation-list empty-detail";
  citationList.textContent = "Waiting for citation verification.";
}

function setIdle() {
  runButton.disabled = false;
  runButton.textContent = "Run target discovery";
}

async function loadResult(jobId) {
  const response = await fetch(`/jobs/${jobId}/result?format=json`);
  if (!response.ok) {
    throw new Error(`result ${response.status}`);
  }
  const payload = await response.json();
  renderResult(jobId, payload.report);
}

function streamJob(jobId) {
  const events = new EventSource(`/jobs/${jobId}/stream`);
  const updateFromEvent = (message) => {
    const payload = JSON.parse(message.data);
    renderSteps(payload.state?.completed_steps || []);
  };

  events.addEventListener("step_finished", updateFromEvent);
  events.addEventListener("step_completed", updateFromEvent);
  events.addEventListener("complete", async (message) => {
    const payload = JSON.parse(message.data);
    renderSteps(payload.state?.completed_steps || []);
    setText(jobStatus, "succeeded");
    events.close();
    await loadResult(jobId);
    setIdle();
  });
  events.addEventListener("step_failed", (message) => {
    const payload = JSON.parse(message.data);
    setText(jobStatus, "failed");
    targetsBody.innerHTML = `<tr><td colspan="7" class="empty-cell">${payload.error}</td></tr>`;
  });
  events.addEventListener("failed", (message) => {
    const payload = JSON.parse(message.data);
    setText(jobStatus, "failed");
    targetsBody.innerHTML = `<tr><td colspan="7" class="empty-cell">${payload.error}</td></tr>`;
    events.close();
    setIdle();
  });
  events.onerror = () => {
    events.close();
    setIdle();
  };
}

async function submitDisease(disease) {
  setRunning(disease);
  const response = await fetch("/jobs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ disease }),
  });
  if (!response.ok) {
    throw new Error(`submit ${response.status}`);
  }
  const payload = await response.json();
  streamJob(payload.job_id);
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    const payload = await response.json();
    systemStatus.classList.toggle("ok", payload.status === "ok");
    systemStatus.classList.toggle("bad", payload.status !== "ok");
    systemStatus.querySelector("span:last-child").textContent = payload.status;
    renderServices(payload);
  } catch {
    systemStatus.classList.add("bad");
    systemStatus.querySelector("span:last-child").textContent = "offline";
    renderServices(null);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const disease = diseaseInput.value.trim();
  if (!disease) {
    diseaseInput.focus();
    return;
  }
  try {
    await submitDisease(disease);
  } catch (error) {
    targetsBody.innerHTML = `<tr><td colspan="7" class="empty-cell">${error}</td></tr>`;
    setText(jobStatus, "failed");
    setIdle();
  }
});

renderSteps([]);
renderCoverageMap();
renderKnowledgeGraph(null);
resetSummary();
renderServices(currentHealth);
checkHealth();
