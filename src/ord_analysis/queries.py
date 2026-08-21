"""Reusable queries against a local ORD PostgreSQL database.

Each function takes a SQLAlchemy `Engine` (see `ord_analysis.db.get_engine`)
and returns a `pandas.DataFrame`. Queries are written against the ORM
mappers in `ord_schema.orm.mappers.Mappers`, which is the schema's documented
query interface (see `ord_schema/orm/README.md`), rather than against the raw
`ord.*` table names directly.
"""

import pandas as pd
from ord_schema.orm.mappers import Mappers
from ord_schema.orm.rdkit_mappers import FingerprintType, RDKitMols
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

# Seconds-per-unit for converting Time messages to a common "hours" scale.
_HOURS_PER_UNIT = {
    "SECOND": 1 / 3600,
    "MINUTE": 1 / 60,
    "HOUR": 1,
    "DAY": 24,
}

# DOIs of the two large USPTO-mined datasets, used to separate "mined" bulk
# data from smaller hand-curated submissions in size/quality comparisons.
USPTO_DOIS = ("10.6084/m9.figshare.5104873.v1", "10.1039/C8SC04228D")


def dataset_overview(engine: Engine) -> pd.DataFrame:
    """Returns one row per dataset with a USPTO-derived flag.

    Reaction counts aren't included here -- use `reaction_counts_by_dataset`,
    which derives them with `COUNT(*)` over `ord.reaction` rather than trusting
    a cached counter (some older ORD database builds don't even have one).
    """
    query = select(
        Mappers.Dataset.dataset_id,
        Mappers.Dataset.name,
        Mappers.Dataset.description,
    )
    with Session(engine) as session:
        df = pd.DataFrame(session.execute(query).all())
    df["is_uspto"] = df["name"].str.contains("uspto", case=False, na=False)
    return df


def reaction_counts_by_dataset(engine: Engine) -> pd.DataFrame:
    """Returns reaction counts per dataset, joined with provenance to flag USPTO-mined reactions."""
    query = (
        select(
            Mappers.Dataset.dataset_id,
            Mappers.ReactionProvenance.is_mined,
            Mappers.ReactionProvenance.doi,
        )
        .select_from(Mappers.Reaction)
        .join(Mappers.Dataset)
        .join(Mappers.ReactionProvenance)
    )
    with Session(engine) as session:
        df = pd.DataFrame(session.execute(query).all())
    df["is_uspto"] = df["doi"].isin(USPTO_DOIS)
    return df.groupby(["dataset_id", "is_uspto"]).size().reset_index(name="count")


def reaction_times(engine: Engine) -> pd.DataFrame:
    """Returns ReactionOutcome.reaction_time values, converted to a common "hours" column.

    Time values are stored with heterogeneous units (SECOND/MINUTE/HOUR/DAY);
    this vectorizes the unit conversion instead of mutating per-unit slices.
    """
    query = select(Mappers.Time.value, Mappers.Time.precision, Mappers.Time.units).where(
        Mappers.Time.ord_schema_context == "ReactionOutcome.reaction_time"
    )
    with Session(engine) as session:
        df = pd.DataFrame(session.execute(query).all())
    df = df.dropna(subset=["value", "units"])
    df["hours"] = df["value"] * df["units"].map(_HOURS_PER_UNIT)
    return df.dropna(subset=["hours"])


def yields(engine: Engine) -> pd.DataFrame:
    """Returns product yield measurements joined with reaction provenance.

    Product SMILES are read from `CompoundIdentifier` (type "SMILES") rather
    than a `ProductCompound.smiles` convenience column -- identifiers are the
    canonical source in the ORD schema and this works across ord_schema/database
    versions that don't materialize that column.
    """
    query = (
        select(
            Mappers.Reaction.reaction_id,
            Mappers.Dataset.dataset_id,
            Mappers.ReactionProvenance.is_mined,
            Mappers.ReactionProvenance.doi,
            Mappers.CompoundIdentifier.value.label("smiles"),
            Mappers.ProductMeasurement.type,
            Mappers.Percentage.value,
            Mappers.Percentage.precision,
        )
        .select_from(Mappers.Reaction)
        .join(Mappers.Dataset)
        .join(Mappers.ReactionProvenance)
        .join(Mappers.ReactionOutcome)
        .join(Mappers.ProductCompound)
        .join(Mappers.ProductMeasurement)
        .join(Mappers.Percentage)
        .join(Mappers.CompoundIdentifier)
        .where(Mappers.ProductMeasurement.type == "YIELD")
        .where(Mappers.CompoundIdentifier.type == "SMILES")
    )
    with Session(engine) as session:
        df = pd.DataFrame(session.execute(query).all())
    df["is_uspto"] = df["doi"].isin(USPTO_DOIS)
    return df


def time_and_yield(engine: Engine) -> pd.DataFrame:
    """Returns paired (reaction time, yield) values for outcomes that report both.

    Both `Time` and `Percentage` are joined from the same `ReactionOutcome` row,
    so each pair corresponds to a single reported outcome.
    """
    query = (
        select(
            Mappers.Reaction.reaction_id,
            Mappers.ReactionProvenance.is_mined,
            Mappers.Time.value.label("reaction_time_value"),
            Mappers.Time.units.label("reaction_time_units"),
            Mappers.Percentage.value.label("yield_value"),
        )
        .select_from(Mappers.ReactionOutcome)
        .join(Mappers.Reaction)
        .join(Mappers.ReactionProvenance)
        .join(Mappers.Time)
        .join(Mappers.ProductCompound)
        .join(Mappers.ProductMeasurement)
        .join(Mappers.Percentage)
        .where(Mappers.Time.ord_schema_context == "ReactionOutcome.reaction_time")
        .where(Mappers.ProductMeasurement.type == "YIELD")
    )
    with Session(engine) as session:
        df = pd.DataFrame(session.execute(query).all())
    df = df.dropna(subset=["reaction_time_value", "reaction_time_units"])
    df["reaction_time_hours"] = df["reaction_time_value"] * df["reaction_time_units"].map(_HOURS_PER_UNIT)
    return df.dropna(subset=["reaction_time_hours"])


def top_compounds(engine: Engine, role: str = "PRODUCT", limit: int = 50) -> pd.DataFrame:
    """Returns the most frequent product compound SMILES for a given reaction_role.

    `role` matches `ProductCompound.reaction_role` values, e.g. "PRODUCT".
    """
    query = (
        select(Mappers.CompoundIdentifier.value.label("smiles"))
        .select_from(Mappers.ProductCompound)
        .join(Mappers.CompoundIdentifier)
        .where(Mappers.ProductCompound.reaction_role == role)
        .where(Mappers.CompoundIdentifier.type == "SMILES")
    )
    with Session(engine) as session:
        df = pd.DataFrame(session.execute(query).all())
    counts = df["smiles"].value_counts().reset_index()
    counts.columns = ["smiles", "count"]
    return counts.head(limit)


def substructure_search(engine: Engine, smarts: str, limit: int = 25) -> list[str]:
    """Returns reaction_ids of reactions with an input compound matching a SMARTS pattern.

    Requires the RDKit PostgreSQL cartridge (see docs/local_ord_database.md). Joins
    to `rdkit.mols` by SMILES value rather than a `rdkit_mol_id` foreign key, since
    the cartridge fundamentally links by structure (see `ord_schema.orm.database`'s
    own `_update_rdkit_mols`), and not every ORD database materializes that FK.
    """
    query = (
        select(Mappers.Reaction.reaction_id)
        .select_from(Mappers.Reaction)
        .join(Mappers.ReactionInput)
        .join(Mappers.Compound)
        .join(Mappers.CompoundIdentifier)
        .join(RDKitMols, RDKitMols.smiles == Mappers.CompoundIdentifier.value)
        .where(Mappers.CompoundIdentifier.type == "SMILES")
        .where(RDKitMols.matches_smarts(smarts))
        .distinct()
        .limit(limit)
    )
    with Session(engine) as session:
        return [row[0] for row in session.execute(query).all()]


def similarity_search(
    engine: Engine,
    smiles: str,
    threshold: float = 0.5,
    fingerprint: FingerprintType = FingerprintType.MORGAN_BFP,
    limit: int = 25,
) -> list[str]:
    """Returns reaction_ids of reactions with an input compound Tanimoto-similar to a query SMILES.

    Requires the RDKit PostgreSQL cartridge (see docs/local_ord_database.md). See
    `substructure_search` for why the join to `rdkit.mols` goes by SMILES value.
    """
    query = (
        select(Mappers.Reaction.reaction_id)
        .select_from(Mappers.Reaction)
        .join(Mappers.ReactionInput)
        .join(Mappers.Compound)
        .join(Mappers.CompoundIdentifier)
        .join(RDKitMols, RDKitMols.smiles == Mappers.CompoundIdentifier.value)
        .where(Mappers.CompoundIdentifier.type == "SMILES")
        .where(RDKitMols.tanimoto(smiles, fingerprint) > threshold)
        .distinct()
        .limit(limit)
    )
    with Session(engine) as session:
        return [row[0] for row in session.execute(query).all()]
