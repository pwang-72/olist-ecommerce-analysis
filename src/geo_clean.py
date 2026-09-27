import html
import re
import unicodedata
from urllib.parse import unquote
import pandas as pd
import re

def normalize_city(name):
    """
    Normalize a city or locality name for consistent string matching.

    The normalization performs the following steps:

    1. Return missing values unchanged.
    2. Decode URL-encoded and HTML-escaped characters.
    3. Convert text to lowercase and strip leading/trailing whitespace.
    4. Remove accents and other Unicode combining marks.
    5. Replace common separators/punctuation with spaces:
       - backtick (`) 
       - apostrophe (')
       - acute accent (´)
       - hyphen (-)
    6. Collapse repeated whitespace into a single space.

    Examples
    --------
    'São Paulo' -> 'sao paulo'
    'Andirá-PR' -> 'andira pr'
    "D'Oeste" -> 'd oeste'

    Parameters
    ----------
    name : str or scalar
        City or locality name to normalize.

    Returns
    -------
    str or scalar
        Normalized city name. Missing values are returned unchanged.
    """

    if pd.isna(name):
        return name

    # Decode malformed URL / HTML encodings.
    name = unquote(name)
    name = html.unescape(name)

    # Lowercase and remove surrounding whitespace.
    name = name.lower().strip()

    # Remove accents and other combining marks.
    name = "".join(
        c
        for c in unicodedata.normalize("NFKD", name)
        if not unicodedata.combining(c)
    )

    # Treat common separators/punctuation as spaces:
    # `  '  ´  -
    name = re.sub(r"[`'´\-]", " ", name)

    # Collapse repeated whitespace.
    name = re.sub(r"\s+", " ", name).strip()

    return name

def resolve_municipalities(
    places: pd.DataFrame,
    municipality_ref: pd.DataFrame,
    district_ref: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:

    """
    Resolve locality labels to official Brazilian municipalities.

    The function matches normalized locality names in ``places`` against
    official municipality and district reference tables. Matching is
    performed conservatively in the following order:

    1. Exact municipality match
        Match ``(state_name, city_norm)`` to
        ``(state_name, municipality_norm)``.

    2. Exact district match
        Match ``(state_name, city_norm)`` to
        ``(state_name, district_norm)``. A district-name match is accepted
        only when that district name maps to exactly one municipality within
        the state.

    3. District + parent municipality match
        For unresolved locality strings containing an explicit parent
        municipality, such as ``"district (municipality)"``, extract the
        district and parent municipality and require both to match the
        district reference table.

    Rows that cannot be resolved by any of these rules are returned
    unchanged rather than assigned through fuzzy or heuristic matching.

    Parameters
    ----------
    places : pandas.DataFrame
        Locality records to resolve.

        Required columns:
        - ``state_name`` :
            Full state name used for matching, e.g. ``"São Paulo"``.
        - ``city_norm`` :
            Normalized locality name.

        Any additional columns are allowed and are preserved in both the
        resolved and unresolved outputs.

        Requirements:
        - ``state_name`` must use the same state naming convention as the
            reference tables.
        - ``city_norm`` must be produced using the same normalization
            procedure as ``municipality_norm`` and ``district_norm``.
        - Each row should represent the unit of observation that should be
            preserved in the output. The function does not remove duplicate
            rows from ``places``.

    municipality_ref : pandas.DataFrame
        Municipality-level reference table.

        Required columns:
        - ``state_name`` :
            Full state name.
        - ``municipality_norm`` :
            Normalized official municipality name.
        - ``municipality_full_code`` :
            Official municipality identifier, such as the full IBGE
            municipality code.
        - ``municipality_name`` :
            Official municipality name.

        Requirements:
        - ``municipality_norm`` must use the same normalization procedure
            as ``places["city_norm"]``.
        - ``(state_name, municipality_norm)`` should identify a single
            municipality. Conflicting municipality records for the same key
            can cause one input row to produce multiple merged rows.
        - ``municipality_full_code`` should be non-null for valid reference
            records because its presence is used to determine whether a match
            succeeded.

    district_ref : pandas.DataFrame
        District-level reference table linking districts to their parent
        municipalities.

        Required columns:
        - ``state_name`` :
            Full state name.
        - ``district_norm`` :
            Normalized official district name.
        - ``municipality_norm`` :
            Normalized name of the district's parent municipality.
        - ``municipality_full_code`` :
            Official identifier of the parent municipality.
        - ``municipality_name`` :
            Official name of the parent municipality.

        Requirements:
        - ``district_norm`` and ``municipality_norm`` must use the same
            normalization procedure as ``places["city_norm"]``.
        - Multiple districts with the same normalized name within a state
            are allowed. For an exact district match, the name is used only
            when all matching reference rows point to one municipality.
        - The combination of state, district, and parent municipality should
            identify an unambiguous municipality for the district-with-parent
            matching stage.
        - ``municipality_full_code`` should be non-null for valid reference
            records.

    Returns
    -------
    resolved : pandas.DataFrame
        Successfully resolved locality records.

        Contains all original columns from ``places`` plus:
        - ``municipality_full_code`` :
            Official code of the resolved municipality.
        - ``municipality_name`` :
            Official name of the resolved municipality.
        - ``match_type`` :
            Method by which the row was resolved. One of:
            ``"municipality_exact"``, ``"district_exact"``, or
            ``"district_with_parent"``.

        Temporary matching columns from the reference tables, such as
        ``municipality_norm`` and ``district_norm``, and parsing columns such
        as ``locality_candidate`` and ``parent_candidate``, are not retained.

    unresolved : pandas.DataFrame
        Locality records that could not be resolved by any matching rule.

        Contains exactly the original columns from ``places``. No temporary
        matching or parsing columns are retained.

    Notes
    -----
    This function deliberately does not use fuzzy matching. Failed matches
    are retained in ``unresolved`` for later inspection or treatment.

    Because resolved rows are concatenated by matching stage, the row order
    of ``resolved`` is not guaranteed to be the same as the original order
    in ``places``.
    """
        
    place_cols = places.columns.tolist()
    resolved_cols = place_cols + [
        "municipality_full_code",
        "municipality_name",
        "match_type",
    ]

    resolved_parts = []

    # Municipality match

    municipality_lookup = (
        municipality_ref[
            [
                "state_name",
                "municipality_norm",
                "municipality_full_code",
                "municipality_name",
            ]
        ]
        .drop_duplicates()
    )

    matched = places.merge(
        municipality_lookup,
        left_on=["state_name", "city_norm"],
        right_on=["state_name", "municipality_norm"],
        how="left",
    )

    municipality_mask = matched["municipality_full_code"].notna()

    matched["match_type"] = pd.NA
    matched.loc[
        municipality_mask,
        "match_type",
    ] = "municipality_exact"

    resolved_parts.append(
        matched.loc[
            municipality_mask,
            resolved_cols,
        ].copy()
    )

    unmatched = matched.loc[
        ~municipality_mask,
        place_cols,
    ].copy()

    # District match

    district_unique = (
        district_ref
        .groupby(
            ["state_name", "district_norm"],
            group_keys=False,
        )
        .filter(
            lambda x:
            x["municipality_full_code"].nunique() == 1
        )
        [
            [
                "state_name",
                "district_norm",
                "municipality_full_code",
                "municipality_name",
            ]
        ]
        .drop_duplicates(
            subset=["state_name", "district_norm"]
        )
    )

    district_matches = unmatched.merge(
        district_unique,
        left_on=["state_name", "city_norm"],
        right_on=["state_name", "district_norm"],
        how="left",
    )

    district_mask = (
        district_matches["municipality_full_code"].notna()
    )

    district_matches["match_type"] = pd.NA
    district_matches.loc[
        district_mask,
        "match_type",
    ] = "district_exact"

    resolved_parts.append(
        district_matches.loc[
            district_mask,
            resolved_cols,
        ].copy()
    )

    # District + parent match

    unmatched = district_matches.loc[
        ~district_mask,
        place_cols,
    ].copy()

    tmp = unmatched["city_norm"].str.extract(
        r"^(.*?)\s*\((.*?)\)\s*(?:distrito)?$"
    )

    unmatched["locality_candidate"] = tmp[0].str.strip()
    unmatched["parent_candidate"] = tmp[1].str.strip()

    district_parent_ref = (
        district_ref[
            [
                "state_name",
                "district_norm",
                "municipality_norm",
                "municipality_name",
                "municipality_full_code",
            ]
        ]
        .drop_duplicates()
    )

    district_parent_matches = unmatched.merge(
        district_parent_ref,
        left_on=[
            "state_name",
            "locality_candidate",
            "parent_candidate",
        ],
        right_on=[
            "state_name",
            "district_norm",
            "municipality_norm",
        ],
        how="left",
    )

    parent_mask = (
        district_parent_matches["municipality_full_code"].notna()
    )

    district_parent_matches["match_type"] = pd.NA
    district_parent_matches.loc[
        parent_mask,
        "match_type",
    ] = "district_with_parent"

    resolved_parts.append(
        district_parent_matches.loc[
            parent_mask,
            resolved_cols,
        ].copy()
    )

    resolved = pd.concat(
    resolved_parts,
    ignore_index=True,
    )

    unresolved = district_parent_matches.loc[
        ~parent_mask,
        place_cols,
    ].copy()

    return resolved, unresolved


def _extract_city_from_surface_form(
    city: str,
    state_name: str,
) -> str | None:
    """
    Extract a city candidate from simple address-like surface forms.

    The separate state_name column is treated as the authoritative
    state information. A trailing state qualifier in the city string
    is removed only when it matches either:
        - the full state name in state_name;
        - the corresponding state abbreviation;
        - Brazil.

    Examples
    --------
    city = 'lages - sc'
    state_name = 'Santa Catarina'
        -> 'lages'

    city = 'sao paulo - sp'
    state_name = 'São Paulo'
        -> 'sao paulo'

    city = 'jacarei / sao paulo'
    state_name = 'São Paulo'
        -> 'jacarei'

    city = 'rio de janeiro, rio de janeiro, brasil'
    state_name = 'Rio de Janeiro'
        -> 'rio de janeiro'

    city = 'lages - sp'
    state_name = 'Santa Catarina'
        -> None

    Returns
    -------
    str | None
        Extracted city candidate if the surface form can be cleaned
        safely; otherwise None.
    """

    if pd.isna(city):
        return None

    city = str(city).strip()

    # Split only separators that clearly behave like
    # address/location delimiters.
    parts = re.split(
        r"\s*[,/]\s*|\s+-\s+",
        city,
    )

    parts = [
        part.strip()
        for part in parts
        if part.strip()
    ]

    # No surface-format problem to clean.
    if len(parts) <= 1:
        return None

    # ---------------------------------------------------------
    # State reference
    # ---------------------------------------------------------

    state_abbr_map = {
        "AC": "Acre",
        "AL": "Alagoas",
        "AP": "Amapá",
        "AM": "Amazonas",
        "BA": "Bahia",
        "CE": "Ceará",
        "DF": "Distrito Federal",
        "ES": "Espírito Santo",
        "GO": "Goiás",
        "MA": "Maranhão",
        "MT": "Mato Grosso",
        "MS": "Mato Grosso do Sul",
        "MG": "Minas Gerais",
        "PA": "Pará",
        "PB": "Paraíba",
        "PR": "Paraná",
        "PE": "Pernambuco",
        "PI": "Piauí",
        "RJ": "Rio de Janeiro",
        "RN": "Rio Grande do Norte",
        "RS": "Rio Grande do Sul",
        "RO": "Rondônia",
        "RR": "Roraima",
        "SC": "Santa Catarina",
        "SP": "São Paulo",
        "SE": "Sergipe",
        "TO": "Tocantins",
    }

    if pd.isna(state_name):
        state_norm = None
        state_abbr = None

    else:
        state_norm = normalize_city(state_name)

        # Reverse the abbreviation -> full-name mapping because
        # state_name contains the full state name.
        state_name_to_abbr = {
            normalize_city(full_name): abbr
            for abbr, full_name in state_abbr_map.items()
        }

        state_abbr = state_name_to_abbr.get(
            state_norm
        )

    # Components that are allowed to be removed from the end.
    removable = {
        state_norm,
        (
            normalize_city(state_abbr)
            if state_abbr is not None
            else None
        ),
        "brasil",
        "brazil",
    }

    removable.discard(None)

    # ---------------------------------------------------------
    # Remove trailing geographic qualifiers only
    # ---------------------------------------------------------

    while (
        len(parts) > 1
        and normalize_city(parts[-1]) in removable
    ):
        parts.pop()

    # Surface cleanup is accepted only when all trailing
    # components have been safely explained and exactly one
    # city component remains.
    if len(parts) == 1:
        return parts[0]

    return None


def resolve_surface_city_names(
    places: pd.DataFrame,
    municipality_ref: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Resolve simple surface-format problems in the city column.

    The function:
    1. extracts a possible city candidate from an address-like
       city string;
    2. normalizes the candidate;
    3. validates the candidate against the official municipality
       reference using the separate state_name column;
    4. returns resolved and unresolved DataFrames.

    The state_name column is treated as authoritative. A state
    abbreviation or state name embedded in the city string is used
    only as a removable surface qualifier and cannot override
    state_name.

    All original input columns are preserved.

    For resolved rows:
        - city is preserved;
        - city_norm is replaced by the normalized cleaned candidate;
        - municipality_full_code is added;
        - municipality_name is added;
        - match_type is added.

    For unresolved rows:
        - all original input columns are returned unchanged.

    Returns
    -------
    resolved : pd.DataFrame
        Successfully resolved rows, containing all original columns
        plus municipality_full_code, municipality_name, and match_type.

    unresolved : pd.DataFrame
        Rows that could not be safely resolved, containing exactly
        the original input columns.
    """

    places = places.copy()

    # Save the original input schema before adding working columns.
    place_cols = places.columns.tolist()

    # Temporary unique identifier so that the function does not
    # depend on the DataFrame index being unique.
    places["_row_id"] = range(len(places))

    # ---------------------------------------------------------
    # 1. Generate surface-cleaning candidate
    # ---------------------------------------------------------

    places["_city_candidate"] = places.apply(
        lambda row: _extract_city_from_surface_form(
            row["city"],
            row["state_name"],
        ),
        axis=1,
    )

    places["_city_candidate_norm"] = (
        places["_city_candidate"]
        .map(normalize_city)
    )

    # ---------------------------------------------------------
    # 2. Prepare official municipality reference
    # ---------------------------------------------------------

    ref = (
        municipality_ref[
            [
                "state_name",
                "municipality_norm",
                "municipality_full_code",
                "municipality_name",
            ]
        ]
        .drop_duplicates()
        .copy()
    )

    # ---------------------------------------------------------
    # 3. Validate candidate against municipality + state
    # ---------------------------------------------------------

    matched = places.merge(
        ref,
        left_on=[
            "state_name",
            "_city_candidate_norm",
        ],
        right_on=[
            "state_name",
            "municipality_norm",
        ],
        how="left",
        validate="m:1",
    )

    # A row is resolved only when:
    # 1. surface cleanup produced a candidate; and
    # 2. that candidate is an official municipality in the
    #    state specified by the separate state_name column.
    resolved_mask = (
        matched["_city_candidate_norm"].notna()
        & matched["municipality_full_code"].notna()
    )

    resolved_ids = set(
        matched.loc[
            resolved_mask,
            "_row_id",
        ]
    )

    # ---------------------------------------------------------
    # 4. Construct resolved output
    # ---------------------------------------------------------

    # Use matched directly rather than rebuilding from places.
    # This ensures that _city_candidate_norm and the official
    # municipality information are still available.
    resolved = matched.loc[
        resolved_mask
    ].copy()

    # Preserve the original city string but correct city_norm.
    resolved["city_norm"] = (
        resolved["_city_candidate_norm"]
    )

    resolved["match_type"] = "surface_cleanup"

    # Keep all original columns plus official resolution fields.
    # Working columns such as _row_id and _city_candidate_norm
    # are therefore excluded automatically.
    resolved = resolved[
        place_cols
        + [
            "municipality_full_code",
            "municipality_name",
            "match_type",
        ]
    ].copy()

    # ---------------------------------------------------------
    # 5. Construct unresolved output
    # ---------------------------------------------------------

    unresolved = (
        places.loc[
            ~places["_row_id"].isin(resolved_ids),
            place_cols,
        ]
        .copy()
    )

    return resolved, unresolved

def prepare_toponym_reference(
    toponym_raw: pd.DataFrame,
    *,
    old_name_col: str,
    new_name_col: str,
    state_col: str,
) -> pd.DataFrame:
    """
    Prepare the locally downloaded IBGE toponym table
    for historical-name matching.
    """

    ref = toponym_raw.copy()

    ref = ref.rename(
        columns={
            old_name_col: "old_name",
            new_name_col: "new_name",
            state_col: "candidate_state",
        }
    )

    ref["old_name_norm"] = (
        ref["old_name"]
        .map(normalize_city)
    )

    ref["new_name_norm"] = (
        ref["new_name"]
        .map(normalize_city)
    )

    return ref


def find_historical_name_candidates(
    city_norm: str,
    toponym_ref: pd.DataFrame,
) -> pd.DataFrame:
    """
    Search city_norm in both the old-name and new-name columns
    of the IBGE historical toponym reference.

    State is not used to restrict the search at this stage.
    """

    if pd.isna(city_norm):
        return pd.DataFrame(
            columns=[
                "candidate_no",
                "n_candidates",
                "matched_name",
                "matched_column",
                "municipality_candidate",
                "state_code",
                "old_name",
                "new_name",
            ]
        )

    # Match old municipality names.
    old_matches = (
        toponym_ref.loc[
            toponym_ref["old_name_norm"] == city_norm,
            [
                "old_name",
                "new_name",
                "state_code",
            ],
        ]
        .copy()
    )

    old_matches["matched_name"] = old_matches["old_name"]
    old_matches["matched_column"] = "old_name"

    # The newer name is the municipality candidate.
    old_matches["municipality_candidate"] = (
        old_matches["new_name"]
    )

    # Match newer municipality names.
    new_matches = (
        toponym_ref.loc[
            toponym_ref["new_name_norm"] == city_norm,
            [
                "old_name",
                "new_name",
                "state_code",
            ],
        ]
        .copy()
    )

    new_matches["matched_name"] = new_matches["new_name"]
    new_matches["matched_column"] = "new_name"

    # It already matches the newer name.
    new_matches["municipality_candidate"] = (
        new_matches["new_name"]
    )

    candidates = pd.concat(
        [old_matches, new_matches],
        ignore_index=True,
    ).drop_duplicates()

    if candidates.empty:
        return candidates

    candidates.insert(
        0,
        "candidate_no",
        range(1, len(candidates) + 1),
    )

    candidates.insert(
        1,
        "n_candidates",
        len(candidates),
    )

    return candidates[
        [
            "candidate_no",
            "n_candidates",
            "matched_name",
            "matched_column",
            "municipality_candidate",
            "state_code",
            "old_name",
            "new_name",
        ]
    ]


def filter_historical_candidates_by_state(
    candidates: pd.DataFrame,
    state_name: str,
) -> pd.DataFrame:
    """
    Keep historical candidates whose IBGE UF code agrees with
    the original Olist state.

    Parameters
    ----------
    candidates : pd.DataFrame
        Historical-name candidates returned by
        find_historical_name_candidates().

    state_name : str
        Original full state name from the Olist record.

    Returns
    -------
    pd.DataFrame
        Candidates consistent with the original state.
    """

    IBGE_STATE_CODE = {
        "Rondônia": 11,
        "Acre": 12,
        "Amazonas": 13,
        "Roraima": 14,
        "Pará": 15,
        "Amapá": 16,
        "Tocantins": 17,
        "Maranhão": 21,
        "Piauí": 22,
        "Ceará": 23,
        "Rio Grande do Norte": 24,
        "Paraíba": 25,
        "Pernambuco": 26,
        "Alagoas": 27,
        "Sergipe": 28,
        "Bahia": 29,
        "Minas Gerais": 31,
        "Espírito Santo": 32,
        "Rio de Janeiro": 33,
        "São Paulo": 35,
        "Paraná": 41,
        "Santa Catarina": 42,
        "Rio Grande do Sul": 43,
        "Mato Grosso do Sul": 50,
        "Mato Grosso": 51,
        "Goiás": 52,
        "Distrito Federal": 53,
    }

    if candidates.empty:
        return candidates.copy()

    state_code = IBGE_STATE_CODE.get(state_name)

    if state_code is None:
        return candidates.iloc[0:0].copy()

    return (
        candidates.loc[
            pd.to_numeric(
                candidates["state_code"],
                errors="coerce", #? 
            ) == state_code
        ]
        .copy()
        .reset_index(drop=True)
    )


def resolve_historical_city_names(
    places: pd.DataFrame,
    municipality_ref: pd.DataFrame,
    toponym_ref: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Resolve historical municipality names using a locally stored
    IBGE municipal toponym-change reference.

    Resolution procedure
    --------------------
    1. Search city_norm in BOTH old-name and new-name fields
       of the historical reference.
    2. Convert the historical IBGE state code to the corresponding
       full state name and compare it with the original Olist state.
    3. Validate the resulting municipality candidate against
       the current official municipality reference.
    4. Resolve a row only when exactly one distinct current
       municipality remains.

    Parameters
    ----------
    places : pd.DataFrame
        Unresolved location records.

        Expected columns:
        - city_norm
        - state_name

    municipality_ref : pd.DataFrame
        Current official municipality reference.

        Expected columns:
        - state_name
        - municipality_norm
        - municipality_full_code
        - municipality_name

    toponym_ref : pd.DataFrame
        Prepared locally downloaded IBGE historical-name table.

        Expected columns:
        - old_name
        - new_name
        - old_name_norm
        - new_name_norm
        - candidate_state

        candidate_state is expected to contain the numeric
        two-digit IBGE UF code.

    Returns
    -------
    resolved : pd.DataFrame
        Original columns plus:
        - municipality_full_code
        - municipality_name
        - match_type

        city is preserved.
        city_norm is replaced with the normalized name of the
        current official municipality.

    unresolved : pd.DataFrame
        Original input rows that could not be resolved uniquely.
        All original columns are preserved unchanged.
    """

    # ---------------------------------------------------------
    # 0. Validate required columns
    # ---------------------------------------------------------

    required_place_cols = {
        "city_norm",
        "state_name",
    }

    required_municipality_cols = {
        "state_name",
        "municipality_norm",
        "municipality_full_code",
        "municipality_name",
    }

    required_toponym_cols = {
        "old_name",
        "new_name",
        "old_name_norm",
        "new_name_norm",
        "candidate_state",
    }

    missing_places = (
        required_place_cols
        - set(places.columns)
    )

    missing_municipalities = (
        required_municipality_cols
        - set(municipality_ref.columns)
    )

    missing_toponyms = (
        required_toponym_cols
        - set(toponym_ref.columns)
    )

    if missing_places:
        raise ValueError(
            f"places is missing columns: {missing_places}"
        )

    if missing_municipalities:
        raise ValueError(
            "municipality_ref is missing columns: "
            f"{missing_municipalities}"
        )

    if missing_toponyms:
        raise ValueError(
            "toponym_ref is missing columns: "
            f"{missing_toponyms}"
        )

    place_cols = places.columns.tolist()

    resolved_cols = (
        place_cols
        + [
            "municipality_full_code",
            "municipality_name",
            "match_type",
        ]
    )

    # ---------------------------------------------------------
    # 1. Working copy and stable row identifier
    # ---------------------------------------------------------

    working = places.copy()

    working["_row_id"] = range(len(working))

    working["_state_norm"] = (
        working["state_name"]
        .map(normalize_city)
    )

    # ---------------------------------------------------------
    # 2. Prepare historical-name reference
    # ---------------------------------------------------------

    historical_ref = (
        toponym_ref[
            [
                "old_name",
                "new_name",
                "old_name_norm",
                "new_name_norm",
                "candidate_state",
            ]
        ]
        .drop_duplicates()
        .copy()
    )

    # IBGE two-digit UF code -> full state name.
    ibge_state_code_to_name = {
        11: "Rondônia",
        12: "Acre",
        13: "Amazonas",
        14: "Roraima",
        15: "Pará",
        16: "Amapá",
        17: "Tocantins",
        21: "Maranhão",
        22: "Piauí",
        23: "Ceará",
        24: "Rio Grande do Norte",
        25: "Paraíba",
        26: "Pernambuco",
        27: "Alagoas",
        28: "Sergipe",
        29: "Bahia",
        31: "Minas Gerais",
        32: "Espírito Santo",
        33: "Rio de Janeiro",
        35: "São Paulo",
        41: "Paraná",
        42: "Santa Catarina",
        43: "Rio Grande do Sul",
        50: "Mato Grosso do Sul",
        51: "Mato Grosso",
        52: "Goiás",
        53: "Distrito Federal",
    }

    # Convert candidate_state safely to numeric first.
    # This also handles values such as 35.0 or "35".
    historical_ref["_candidate_state_code"] = (
        pd.to_numeric(
            historical_ref["candidate_state"],
            errors="coerce",
        )
        .astype("Int64")
    )

    historical_ref["_candidate_state_name"] = (
        historical_ref["_candidate_state_code"]
        .map(ibge_state_code_to_name)
    )

    # Fail explicitly if the historical table contains a
    # non-null state code that is not in the official mapping.
    unknown_state_codes = (
        historical_ref.loc[
            historical_ref[
                "_candidate_state_code"
            ].notna()
            & historical_ref[
                "_candidate_state_name"
            ].isna(),
            "_candidate_state_code",
        ]
        .drop_duplicates()
        .tolist()
    )

    if unknown_state_codes:
        raise ValueError(
            "Unknown IBGE state code(s) in toponym_ref: "
            f"{unknown_state_codes}"
        )

    historical_ref["_candidate_state_norm"] = (
        historical_ref["_candidate_state_name"]
        .map(normalize_city)
    )

    # ---------------------------------------------------------
    # 3. Search BOTH old and new historical names
    # ---------------------------------------------------------

    # city_norm matches a historical old name:
    #
    # old name -> current/new name
    old_matches = working.merge(
        historical_ref,
        left_on="city_norm",
        right_on="old_name_norm",
        how="inner",
    )

    if not old_matches.empty:
        old_matches[
            "municipality_candidate_norm"
        ] = old_matches["new_name_norm"]

        old_matches["_historical_match"] = (
            "old_name"
        )

    # city_norm matches the new/current name recorded in
    # the historical reference.
    new_matches = working.merge(
        historical_ref,
        left_on="city_norm",
        right_on="new_name_norm",
        how="inner",
    )

    if not new_matches.empty:
        new_matches[
            "municipality_candidate_norm"
        ] = new_matches["new_name_norm"]

        new_matches["_historical_match"] = (
            "new_name"
        )

    candidate_frames = []

    if not old_matches.empty:
        candidate_frames.append(old_matches)

    if not new_matches.empty:
        candidate_frames.append(new_matches)

    if not candidate_frames:
        return (
            pd.DataFrame(columns=resolved_cols),
            places.copy(),
        )

    candidates = pd.concat(
        candidate_frames,
        ignore_index=True,
    )

    # ---------------------------------------------------------
    # 4. Compare historical state with original Olist state
    # ---------------------------------------------------------

    candidates = candidates.loc[
        candidates["_state_norm"].eq(
            candidates["_candidate_state_norm"]
        )
    ].copy()

    if candidates.empty:
        return (
            pd.DataFrame(columns=resolved_cols),
            places.copy(),
        )

    # ---------------------------------------------------------
    # 5. Validate against current municipality reference
    # ---------------------------------------------------------

    municipality_lookup = (
        municipality_ref[
            [
                "state_name",
                "municipality_norm",
                "municipality_full_code",
                "municipality_name",
            ]
        ]
        .drop_duplicates()
        .copy()
    )

    municipality_lookup["_ref_state_norm"] = (
        municipality_lookup["state_name"]
        .map(normalize_city)
    )

    validated = candidates.merge(
        municipality_lookup,
        left_on=[
            "_candidate_state_norm",
            "municipality_candidate_norm",
        ],
        right_on=[
            "_ref_state_norm",
            "municipality_norm",
        ],
        how="inner",
        validate="m:1",
    )

    if validated.empty:
        return (
            pd.DataFrame(columns=resolved_cols),
            places.copy(),
        )

    # ---------------------------------------------------------
    # 6. Collapse to distinct current municipalities
    # ---------------------------------------------------------

    municipality_candidates = (
        validated[
            [
                "_row_id",
                "municipality_full_code",
                "municipality_name",
                "municipality_norm",
            ]
        ]
        .drop_duplicates()
        .copy()
    )

    candidate_counts = (
        municipality_candidates
        .groupby("_row_id")[
            "municipality_full_code"
        ]
        .nunique()
    )

    resolved_ids = set(
        candidate_counts[
            candidate_counts == 1
        ].index
    )

    if not resolved_ids:
        return (
            pd.DataFrame(columns=resolved_cols),
            places.copy(),
        )

    # ---------------------------------------------------------
    # 7. Construct resolved output
    # ---------------------------------------------------------

    resolved_info = (
        municipality_candidates.loc[
            municipality_candidates[
                "_row_id"
            ].isin(resolved_ids)
        ]
        .drop_duplicates(
            subset="_row_id"
        )
        .copy()
    )

    resolved = (
        working.loc[
            working["_row_id"].isin(
                resolved_ids
            )
        ]
        .merge(
            resolved_info,
            on="_row_id",
            how="left",
            validate="1:1",
        )
    )

    # Keep original raw city unchanged.
    # Replace city_norm with the normalized current official name.
    resolved["city_norm"] = (
        resolved["municipality_norm"]
    )

    resolved["match_type"] = (
        "historical_name"
    )

    resolved = resolved[
        resolved_cols
    ].copy()

    # ---------------------------------------------------------
    # 8. Construct unresolved output
    # ---------------------------------------------------------

    unresolved = (
        working.loc[
            ~working["_row_id"].isin(
                resolved_ids
            ),
            place_cols,
        ]
        .copy()
    )

    return resolved, unresolved