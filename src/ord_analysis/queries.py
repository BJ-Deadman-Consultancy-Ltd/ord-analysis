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
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

# Seconds-per-unit for converting Time messages to a common "hours" scale.
_HOURS_PER_UNIT = {
    "SECOND": 1 / 3600,
    "MINUTE": 1 / 60,
    "HOUR": 1,
    "DAY": 24,
}

# Conversions from each Temperature.TemperatureUnit to Celsius.
_CELSIUS_FROM_UNIT = {
    "CELSIUS": lambda v: v,
    "FAHRENHEIT": lambda v: (v - 32) * 5 / 9,
    "KELVIN": lambda v: v - 273.15,
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


def dataset_first_reaction_dates(engine: Engine) -> pd.DataFrame:
    """Returns each dataset's earliest ReactionProvenance.record_created timestamp.

    `RecordEvent.time` (a `DateTime`) stores its value as an unparsed string, so it's
    parsed here rather than in SQL. Reactions with no `record_created` set are simply
    absent from the result -- callers should expect some datasets to be missing and
    should treat them as unknown/unsorted rather than assuming full coverage.
    """
    query = (
        select(Mappers.Dataset.dataset_id, Mappers.DateTime.value.label("record_created"))
        .select_from(Mappers.Reaction)
        .join(Mappers.Dataset)
        .join(Mappers.ReactionProvenance)
        .join(Mappers.RecordEvent)
        .join(Mappers.DateTime)
        .where(Mappers.RecordEvent.ord_schema_context == "ReactionProvenance.record_created")
        .where(Mappers.DateTime.ord_schema_context == "RecordEvent.time")
    )
    with Session(engine) as session:
        df = pd.DataFrame(session.execute(query).all())
    df["record_created"] = pd.to_datetime(df["record_created"], errors="coerce")
    return df.groupby("dataset_id")["record_created"].min().reset_index()


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


def temperatures(engine: Engine) -> pd.DataFrame:
    """Returns ReactionConditions.temperature.setpoint values, converted to a common "celsius" column.

    Also includes the apparatus type from `TemperatureConditions.control` (e.g. "OIL_BATH").
    `control` is itself a submessage (`TemperatureControl`, with `type`/`details` fields), not
    a plain enum column, so it needs its own join -- left outer, since most reactions have a
    setpoint but no apparatus recorded.
    """
    query = (
        select(
            Mappers.Temperature.value,
            Mappers.Temperature.units,
            Mappers.TemperatureControl.type.label("control"),
        )
        .select_from(Mappers.TemperatureConditions)
        .join(Mappers.Temperature)
        .join(Mappers.TemperatureControl, isouter=True)
        .where(Mappers.Temperature.ord_schema_context == "TemperatureConditions.setpoint")
    )
    with Session(engine) as session:
        df = pd.DataFrame(session.execute(query).all())
    df = df.dropna(subset=["value", "units"])
    df["celsius"] = df.apply(lambda row: _CELSIUS_FROM_UNIT[row["units"]](row["value"]), axis=1)
    df["control"] = df["control"].fillna("NOT_RECORDED")
    return df


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


def top_input_compounds(engine: Engine, role: str, limit: int = 50) -> pd.DataFrame:
    """Returns the most frequent reaction-input compound SMILES for a given reaction_role.

    `role` matches `Compound.reaction_role` values, e.g. "REACTANT", "SOLVENT". Unlike
    `top_compounds` (which reads `ProductCompound`), this reads `Compound`, the message
    used for `ReactionInput` components (see `05_structure_search.ipynb` for the same
    `Compound`/`CompoundIdentifier` join used to search reaction inputs).
    """
    query = (
        select(Mappers.CompoundIdentifier.value.label("smiles"))
        .select_from(Mappers.Compound)
        .join(Mappers.CompoundIdentifier)
        .where(Mappers.Compound.reaction_role == role)
        .where(Mappers.CompoundIdentifier.type == "SMILES")
    )
    with Session(engine) as session:
        df = pd.DataFrame(session.execute(query).all())
    counts = df["smiles"].value_counts().reset_index()
    counts.columns = ["smiles", "count"]
    return counts.head(limit)


def inputs_per_reaction(engine: Engine) -> pd.DataFrame:
    """Returns the number of ReactionInputs per Reaction, with a curated/USPTO flag.

    Counting is done in SQL (`func.count`/`group_by`) rather than pandas `value_counts`,
    since `Reaction`/`ReactionInput` are large tables (millions of rows) and pulling raw
    child rows into pandas just to count them would be far slower than a SQL GROUP BY.
    """
    query = (
        select(
            Mappers.Reaction.reaction_id,
            Mappers.ReactionProvenance.doi,
            func.count(Mappers.ReactionInput.id).label("n_inputs"),
        )
        .select_from(Mappers.Reaction)
        .join(Mappers.ReactionProvenance)
        .join(Mappers.ReactionInput)
        .group_by(Mappers.Reaction.reaction_id, Mappers.ReactionProvenance.doi)
    )
    with Session(engine) as session:
        df = pd.DataFrame(session.execute(query).all())
    df["is_uspto"] = df["doi"].isin(USPTO_DOIS)
    return df


def components_per_input(engine: Engine) -> pd.DataFrame:
    """Returns the number of Compound components per ReactionInput, with a curated/USPTO flag.

    See `inputs_per_reaction` for why counting is done in SQL rather than pandas --
    `Compound` alone has millions of rows.
    """
    query = (
        select(
            Mappers.ReactionInput.id,
            Mappers.ReactionProvenance.doi,
            func.count(Mappers.Compound.id).label("n_components"),
        )
        .select_from(Mappers.ReactionInput)
        .join(Mappers.Reaction)
        .join(Mappers.ReactionProvenance)
        .join(Mappers.Compound)
        .group_by(Mappers.ReactionInput.id, Mappers.ReactionProvenance.doi)
    )
    with Session(engine) as session:
        df = pd.DataFrame(session.execute(query).all())
    df["is_uspto"] = df["doi"].isin(USPTO_DOIS)
    return df


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
