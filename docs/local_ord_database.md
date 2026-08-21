# Building a local ORD database

This project queries a local PostgreSQL database loaded with data from
[ord-data](https://github.com/open-reaction-database/ord-data), using the
object-relational mapper that ships with
[`ord_schema`](https://github.com/open-reaction-database/ord-schema)
(`ord_schema.orm`). The steps below follow the process documented in
[`ord_schema/orm/README.md`](https://github.com/open-reaction-database/ord-schema/blob/main/ord_schema/orm/README.md).

## 1. Install PostgreSQL with the RDKit cartridge

The RDKit PostgreSQL extension (`rdkit-postgresql`) provides the structure
and similarity search used in [`05_structure_search.ipynb`](../notebooks/05_structure_search.ipynb).
The simplest way to get both Postgres and the extension is a dedicated conda
environment:

```bash
conda env create -f environment.yml
conda activate ord-analysis
pip install -e .   # installs the ord_analysis package used by the notebooks

# Initialize a Postgres data directory and start the server.
export PGDATA="${HOME}/ord-analysis-postgresql"
initdb -U postgres
pg_ctl -l "${PGDATA}/logfile" start

# Create the database.
psql -U postgres postgres -c 'CREATE DATABASE ord;'
```

(`prepare_database()` in the next step also works against a Postgres instance
installed another way -- e.g. a managed Postgres with the RDKit extension
available -- as long as you have a connection string. The RDKit cartridge is
optional: `prepare_database()` degrades gracefully and structure search is
simply unavailable if it's not installed.)

## 2. Set your connection details

Copy `.env.example` to `.env` and fill in your host/port/database/user. The
password is read from the `PGPASSWORD` environment variable instead of a
file, so it never gets written to disk:

```bash
cp .env.example .env
export PGPASSWORD=<your local postgres password>
```

## 3. Create the schema

```python
from dotenv import load_dotenv
from ord_schema.orm.database import prepare_database

from ord_analysis.db import get_engine

load_dotenv()
engine = get_engine()
rdkit_available = prepare_database(engine)
print(f"RDKit cartridge available: {rdkit_available}")
```

This creates the `ord` and `rdkit` Postgres schemas and one table per ORD
protobuf message type (`dataset`, `reaction`, `reaction_outcome`, `compound`,
`product_compound`, `percentage`, `time`, ...). See
[`ord_schema/orm/README.md`](https://github.com/open-reaction-database/ord-schema/blob/main/ord_schema/orm/README.md#database-structure)
for the full structure.

## 4. Load data

Clone [ord-data](https://github.com/open-reaction-database/ord-data)
somewhere on disk (or download a subset with its
`scripts/download_from_huggingface.py`), then bulk-load with the script that
ships in `ord_schema`:

```bash
python -m ord_schema.orm.scripts.add_datasets \
    --pattern "/path/to/ord-data/data/**/*.pb.gz" \
    --database ord \
    --username postgres \
    --host localhost
```

`PGPASSWORD` is picked up automatically if `--password` is omitted. Loading
the full ord-data corpus takes a while and needs a fair amount of disk space
-- for exploring this project, a `--pattern` matching a handful of shards
(e.g. `data/4d/*.pb.gz`) is enough to run every notebook.

To refresh a dataset that's changed on disk, re-run with `--overwrite`.

## 5. Verify

```bash
psql -U postgres ord -c '\dt ord.*'
```

You should see one table per ORD message type. From here, open
[`notebooks/01_setup_and_connection.ipynb`](../notebooks/01_setup_and_connection.ipynb)
to confirm the Python side can connect and query.
