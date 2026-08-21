# ord-analysis

A worked example of standing up your own local copy of the
[Open Reaction Database](https://open-reaction-database.org/) (ORD) and
querying it -- with a growing set of exploratory data analysis and
cheminformatics examples.

## Why

ORD data is published as compressed protocol buffers
([ord-data](https://github.com/open-reaction-database/ord-data)), which is
great for storage but not for ad hoc analysis. `ord_schema` ships an
object-relational mapper that loads that data into PostgreSQL (optionally
with the RDKit cartridge for structure/similarity search), turning it into
something you can query with SQL, SQLAlchemy, or pandas. This repo is a
reproducible walkthrough of that pipeline, plus example analyses.

## Architecture

```
ord-data (protobuf, source of truth)
    │  ord_schema.orm.database.add_dataset()
    ▼
local PostgreSQL  ──schema "ord"──  one table per ORD message type
                  ──schema "rdkit"── molecule/reaction fingerprints
    │  SQLAlchemy ORM (ord_schema.orm.mappers.Mappers)
    ▼
pandas / RDKit  →  notebooks/
```

`src/ord_analysis/` holds the reusable bits (`db.py` for the connection,
`queries.py` for the actual queries) so the notebooks stay focused on
analysis rather than boilerplate.

## Setup

1. `conda env create -f environment.yml && conda activate ord-analysis && pip install -e .`
2. Build a local ORD database and load some data -- see
   [`docs/local_ord_database.md`](docs/local_ord_database.md) for the full
   walkthrough (Postgres + RDKit cartridge install, schema creation, bulk
   loading from an `ord-data` clone).
3. `cp .env.example .env` and fill in your connection details; export
   `PGPASSWORD` rather than putting it in a file.
4. `jupyter lab notebooks/`

> **Note on repo history:** early commits in this repository's git history
> contain a hardcoded database password for an internal, LAN-only address.
> That address is not reachable outside the local network it was on, but the
> credential itself was never meant to be public. All current code reads
> connection details from environment variables instead (see
> [`src/ord_analysis/db.py`](src/ord_analysis/db.py)); nothing in the current
> tree references that database.

## Notebooks

| Notebook | What it demonstrates |
|---|---|
| [`01_setup_and_connection.ipynb`](notebooks/01_setup_and_connection.ipynb) | Connecting to the local DB and listing the `ord`/`rdkit` schemas and tables |
| [`02_dataset_overview.ipynb`](notebooks/02_dataset_overview.ipynb) | Dataset inventory: sizes, curated vs. USPTO-mined split |
| [`03_reaction_conditions_eda.ipynb`](notebooks/03_reaction_conditions_eda.ipynb) | Reaction time and yield distributions, curated vs. mined comparisons, correlations |
| [`04_chemical_space.ipynb`](notebooks/04_chemical_space.ipynb) | Most frequent reactants/products, rendered with RDKit |
| [`05_structure_search.ipynb`](notebooks/05_structure_search.ipynb) | Substructure and Tanimoto similarity search via the RDKit PostgreSQL cartridge |

New notebooks get added here as the set of example queries grows.

## Skills demonstrated

- **SQL / ORM query design** -- querying a normalized, auto-generated
  relational schema via SQLAlchemy's ORM, including multi-table joins and
  polymorphic single-table inheritance (`src/ord_analysis/queries.py`).
- **Exploratory data analysis** -- distribution analysis, unit
  normalization, curated-vs-mined comparisons, and correlation analysis on
  real-world, messy experimental chemistry data.
- **Cheminformatics** -- RDKit-based molecule rendering and PostgreSQL
  cartridge-backed substructure/similarity search over reaction data.

## Related projects

- [ord-schema](https://github.com/open-reaction-database/ord-schema) -- the
  ORD protobuf schema and the `ord_schema.orm` module this project builds on.
- [ord-data](https://github.com/open-reaction-database/ord-data) -- the
  dataset repository this project loads from.
