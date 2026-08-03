# Commerce Knowledge Graph

A production-grade knowledge graph for your commerce platform. It models the
people, products and decisions that drive your business — and the relationships
between them — as a labelled, weighted graph, then reasons over that graph to
answer questions, surface opportunities and generate recommendations.

## What it represents

**Entities (nodes):** products, brands, categories, suppliers, marketplaces,
customers, AI decisions, historical events, price changes, inventory snapshots,
and seasonality signals — plus a generic `other` type so the graph absorbs new
entity kinds without a schema change.

**Relationships (edges):** `belongs_to`, `supplied_by`, `sells_on`, `bought_by`,
`decided_by`, `led_to`, `priced_at`, `has_stock`, `seasonal_in`, `related_to`,
`similar_to`, `has_variant`, `affected_by`, `part_of`. Every edge is weighted
(larger = stronger) and can carry its own attributes (date, quantity, delta...).

```
(customer) --bought_by--> (product) --supplied_by--> (supplier)
                              |                            |
                         belongs_to                   affected_by
                              |                            v
                          (category)               (historical_event)
                              |
                          seasonal_in
                              v
                        (seasonality)
```

## What it supports

| Capability | Endpoint(s) | What it does |
|-----------|-------------|--------------|
| **Graph traversal** | `GET /traversal/{type}/{key}` | BFS from any node, depth-limited |
| **Shortest path** | `GET /path` | Dijkstra (cheapest) path between two nodes |
| **Semantic search** | `GET /search?q=...` | Ranked search over node text (embeddings or lexical cosine) |
| **Relationship discovery** | `GET /related/{type}/{key}` | Find same-type entities related to a node |
| **Recommendation generation** | `GET /recommendations/{type}/{key}` | Weighted composite-score recommendations |
| **Similarity search** | `GET /similarity` | Cosine (embeddings) or Jaccard (neighbours) |
| **Profitable clusters** | `GET /clusters/profitable` | Rank communities by aggregate profit/ROI |
| **Hidden opportunities** | `GET /opportunities` | Structural gaps & risks worth investigating |
| **Explainable reasoning** | `GET /explain/{type}/{key}`, `GET /explain/path` | Step-by-step reasoning for any result |

**API surface for the four headline questions:**

- **Find related products** → `GET /api/v1/knowledge-graph/products/{key}/related`
- **Find related suppliers** → `GET /api/v1/knowledge-graph/suppliers/{key}/related`
- **Find profitable clusters** → `GET /api/v1/knowledge-graph/clusters/profitable`
- **Discover hidden opportunities** → `GET /api/v1/knowledge-graph/opportunities`

## How recommendations are scored

Each candidate accumulates a weighted composite score from graph signals:

| Signal | Weight | Meaning |
|--------|--------|---------|
| `shared_category` | 0.25 | Same category |
| `shared_brand` | 0.20 | Same brand |
| `co_purchased` | 0.25 | Shared customer purchase history |
| `shared_supplier` | 0.15 | Same supplier sources both |
| `neighbor_similarity` | 0.15 | Jaccard overlap of graph neighbourhoods |

Candidates below `recommend_min_score` (default `0.05`) are dropped so results
are meaningful. Every result carries its `signals` and a `reasoning` string so
the "why" is transparent.

## How profitable clusters are found

1. **Community detection** — label-propagation groups nodes into communities.
2. **Aggregation** — each community's aggregate `profit` and mean `roi` come
   from node attributes (fed by your finance/forecast data).
3. **Ranking** — communities that clear `min_cluster_profit` are ranked by
   aggregate profit, with the top products listed.

## Hidden opportunities (structural gaps & risks)

The `opportunities` endpoint scans the graph for patterns like:

- **Unconnected profitable product** — a profitable product with no supplier.
- **Single-supplier dependency** — a profitable product dependent on exactly
  one supplier (supply risk → opportunity to diversify).
- **Under-utilised supplier** — a supplier with few profitable products.
- **Underserved category** — a category with many products but no supplier.
- **Unlisted marketplace** — a profitable product not listed anywhere.

Each opportunity carries a `score`, the involved node ids, and an `explanation`.

## Explainable reasoning

Every recommendation, path and opportunity can be explained. `/explain` returns
the target, each recommended candidate, its score, the contributing signals, and
a natural-language reasoning sentence. `/explain/path` renders a shortest path
hop-by-hop (`node → node → node` with types and labels). All explanations are
deterministic and reference the actual evidence — no black box.

## Storage & future graph databases

The graph is persisted in Postgres in two generic tables:

- `graph_nodes` — entity type, natural `key` (unique per type), label,
  attributes JSON, optional embedding JSON.
- `graph_edges` — source, target, edge type, weight, attributes JSON (unique
  per source+target+type; edges cascade on node delete).

The engine and API depend only on the **`GraphStore` interface**
(`app/knowledge_graph/store.py`). The production implementation is
`PostgresGraphStore`. A future dedicated graph database (Neo4j, Dgraph,
Memgraph, ...) plugs in as a new `GraphStore` subclass with **zero changes** to
the algorithms, semantics, or API.

## Seed data & quick start

`POST /api/v1/knowledge-graph/seed` builds a small representative graph
(products, brands, categories, suppliers, marketplaces, customers, events,
decisions, price changes, inventory, seasonality) that exercises every
capability — including products that trigger each hidden-opportunity pattern.

```bash
# Build the demo graph
curl -X POST .../api/v1/knowledge-graph/seed

# Related products
curl .../api/v1/knowledge-graph/products/ASIN-ERG01/related

# Related suppliers
curl .../api/v1/knowledge-graph/suppliers/acme-mfg/related

# Semantic search
curl ".../api/v1/knowledge-graph/search?q=ergonomic office chair"

# Profitable clusters
curl .../api/v1/knowledge-graph/clusters/profitable

# Hidden opportunities
curl .../api/v1/knowledge-graph/opportunities

# Explain a recommendation
curl .../api/v1/knowledge-graph/explain/product/ASIN-ERG01

# Model your own graph
curl -X POST .../api/v1/knowledge-graph/nodes \
  -H 'Content-Type: application/json' \
  -d '{"node_type":"product","key":"ASIN-X","label":"X","attributes":{"profit":40}}'
```

## Node / edge CRUD

- `POST /nodes` and `POST /nodes/bulk` — upsert nodes (by `node_type` + `key`).
- `GET /nodes`, `GET /nodes/{type}/{key}` — list / fetch.
- `DELETE /nodes/{id}` — delete (edges cascade).
- `POST /edges` and `POST /edges/bulk` — create edges (idempotent upsert).
- `GET /edges`, `DELETE /edges/{id}`.
- `GET /capabilities`, `GET /stats` — supported types & graph inventory.
