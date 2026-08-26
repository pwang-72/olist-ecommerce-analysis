from google.genai import types
import json
import pandas as pd

def analyze_review(review: str, cache_name: str, client, schema, model):
    """
    Send one review to Gemini for structured aspect-based sentiment
    extraction.

    Returns:
        result: Parsed JSON response containing the extracted spans.
        usage_dict: Token-usage information returned by the API.
        response: Raw Gemini response.
    """

    response = client.models.generate_content(
        model=model,
        contents=review,
        config=types.GenerateContentConfig(
            cached_content=cache_name,
            response_mime_type="application/json",
            response_json_schema=schema,
        ),
    )

    result = json.loads(response.text)

    usage = response.usage_metadata

    usage_dict = {
        "input_tokens": getattr(
            usage,
            "prompt_token_count",
            None
        ),
        "output_tokens": getattr(
            usage,
            "candidates_token_count",
            None
        ),
        "total_tokens": getattr(
            usage,
            "total_token_count",
            None
        ),
        "cached_tokens": getattr(
            usage,
            "cached_content_token_count",
            None
        ),
    }

    return result, usage_dict, response

def load_analysis_jsonl(filename):
    results = []

    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            results.append(json.loads(line))

    return results

def get_discourse_weight(
    discourse_role,
    relation,
    discourse_weights=None,
):
    """
    Return the discourse weight for a (discourse_role, relation) pair.

    Invalid combinations return None and are handled separately during
    manual inspection / post-processing.
    """

    if discourse_weights is None:
        discourse_weights = {
            ("none", "none"): 2,
            ("nucleus", "none"): 2,
            ("satellite", "concession_tradeoff"): 1,
            ("satellite", "concession_exclusion"): 0,
        }

    return discourse_weights.get(
        (discourse_role, relation)
    )


def aggregate_aspect_df(
    aspect_df,
    discourse_weights=None,
):
    """
    Aggregate extracted evaluations into one net evaluation per
    review and specific aspect.

    overall_satisfaction is excluded because it represents the
    overall customer evaluation rather than one of the specific
    aspects used for aspect-level aggregation.

    For each review and aspect:

    1. Assign a discourse weight to each valid span.
    2. For each attitude, retain the strongest weight.
    3. Calculate:

           net_weight = positive_weight - negative_weight

    4. If net_weight > 0:
           final attitude = positive
           final weight = net_weight

       If net_weight < 0:
           final attitude = negative
           final weight = abs(net_weight)

       If net_weight == 0:
           positive and negative evaluations cancel, so no result
           is returned for that aspect.

    Returns
    -------
    pandas.DataFrame
        One row per review/aspect after aggregation.
    """

    if discourse_weights is None:
        discourse_weights = {
            ("none", "none"): 2,
            ("nucleus", "none"): 2,
            ("satellite", "concession_tradeoff"): 1,
            ("satellite", "concession_exclusion"): 0,
        }

    # Exclude overall satisfaction from specific-aspect aggregation.
    df = aspect_df[
        aspect_df["aspect"] != "overall_satisfaction"
    ].copy()

    if df.empty:
        return pd.DataFrame(
            columns=[
                "id",
                "review_pt",
                "review_en",
                "text",
                "aspect",
                "attitude",
                "weight",
            ]
        )

    # Assign discourse weights.
    df["weight"] = df.apply(
        lambda row: get_discourse_weight(
            row["discourse_role"],
            row["relation"],
            discourse_weights,
        ),
        axis=1,
    )

    # Remove invalid discourse combinations from automatic aggregation.
    # They can be inspected and manually handled separately.
    df = df[df["weight"].notna()].copy()

    if df.empty:
        return pd.DataFrame(
            columns=[
                "id",
                "review_pt",
                "review_en",
                "text",
                "aspect",
                "attitude",
                "weight",
            ]
        )

    results = []

    # Process each review separately.
    for review_key, review_df in df.groupby(
        ["id", "review_pt", "review_en"],
        dropna=False,
        sort=False,
    ):

        # Process each specific aspect separately.
        for aspect, aspect_df in review_df.groupby(
            "aspect",
            sort=False,
        ):

            attitude_results = {}

            # Find the strongest weight for each attitude.
            for attitude, attitude_df in aspect_df.groupby(
                "attitude",
                sort=False,
            ):

                max_weight = attitude_df["weight"].max()

                strongest = attitude_df[
                    attitude_df["weight"] == max_weight
                ]

                text = "; ".join(
                    strongest["text"].astype(str)
                )

                attitude_results[attitude] = {
                    "text": text,
                    "weight": max_weight,
                }

            positive = attitude_results.get("positive")
            negative = attitude_results.get("negative")
            neutral = attitude_results.get("neutral")

            # ---------------------------------------------------------
            # No positive/negative conflict
            # ---------------------------------------------------------

            if positive is None and negative is None:

                # Only neutral evaluations are present.
                if neutral is not None:
                    results.append({
                        "id": review_key[0],
                        "review_pt": review_key[1],
                        "review_en": review_key[2],
                        "text": neutral["text"],
                        "aspect": aspect,
                        "attitude": "neutral",
                        "weight": neutral["weight"],
                    })

                continue

            if positive is None:

                results.append({
                    "id": review_key[0],
                    "review_pt": review_key[1],
                    "review_en": review_key[2],
                    "text": negative["text"],
                    "aspect": aspect,
                    "attitude": "negative",
                    "weight": negative["weight"],
                })

                continue

            if negative is None:

                results.append({
                    "id": review_key[0],
                    "review_pt": review_key[1],
                    "review_en": review_key[2],
                    "text": positive["text"],
                    "aspect": aspect,
                    "attitude": "positive",
                    "weight": positive["weight"],
                })

                continue

            # ---------------------------------------------------------
            # Positive and negative evaluations both exist.
            # Calculate the signed net weight.
            # ---------------------------------------------------------

            net_weight = (
                positive["weight"]
                - negative["weight"]
            )

            # Exact cancellation.
            if net_weight == 0:
                continue

            if net_weight > 0:
                final_attitude = "positive"
                final_weight = net_weight
                final_text = positive["text"]

            else:
                final_attitude = "negative"
                final_weight = abs(net_weight)
                final_text = negative["text"]

            results.append({
                "id": review_key[0],
                "review_pt": review_key[1],
                "review_en": review_key[2],
                "text": final_text,
                "aspect": aspect,
                "attitude": final_attitude,
                "weight": final_weight,
            })

    return pd.DataFrame(results)


def validate_discourse_relation(aspect_df):
    """
    
    Find rows in aspect_df with invalid discourse_role/relation
    combinations.

    Valid combinations:
        ("none", "none")
        ("nucleus", "none")
        ("satellite", "concession_tradeoff")
        ("satellite", "concession_exclusion")

    Returns
    -------
    pandas.DataFrame
        Rows with invalid discourse annotations, including an
        'validation_error' column.
    """

    valid_combinations = {
        ("none", "none"),
        ("nucleus", "none"),
        ("satellite", "concession_tradeoff"),
        ("satellite", "concession_exclusion"),
    }

    mask = [
        (row["discourse_role"], row["relation"]) not in valid_combinations
        for _, row in aspect_df.iterrows()
    ]

    validation_df = aspect_df.loc[mask].copy()

    if validation_df.empty:
        return validation_df

    validation_df["validation_error"] = validation_df.apply(
        lambda row: (
            f"Invalid combination: "
            f"discourse_role={row['discourse_role']!r}, "
            f"relation={row['relation']!r}"
        ),
        axis=1,
    )

    return validation_df


def remove_overall_satisfaction(prediction_df):
    """
    Remove overall_satisfaction spans from reviews that also contain
    at least one specific aspect.

    If overall_satisfaction is the only aspect in a review, it is kept.

    Returns
    -------
    pandas.DataFrame
        Filtered prediction DataFrame.
    """

    df = prediction_df.copy()

    # Identify reviews that contain at least one specific aspect.
    review_has_specific_aspect = (
        df.assign(
            is_specific=df["aspect"] != "overall_satisfaction"
        )
        .groupby(
            ["id", "review_pt", "review_en"],
            dropna=False
        )["is_specific"]
        .transform("any")
    )

    # Remove overall_satisfaction only from reviews that also
    # contain a specific aspect.
    keep = ~(
        (df["aspect"] == "overall_satisfaction")
        & review_has_specific_aspect
    )

    return df.loc[keep].copy()

def calculate_category_scores(aggregated_df):
    """
    Calculate Product, Seller, and Delivery ratings from aggregated
    aspect-level evaluations.

    The calculation proceeds in two steps:

    1. Calculate an aspect score:
           aspect_score = 3(baseline) + attitude_sign * weight

       where:
           positive -> +1
           neutral  ->  0
           negative -> -1

           weight:
               0 = concession_exclusion
               1 = concession_tradeoff
               2 = none / nucleus

    2. Map each specific aspect to Product, Seller, or Delivery and
       average the aspect scores within each review/category.

    "overall_satisfaction" and "others" are excluded.

    Returns
    -------
    pandas.DataFrame
        Columns:
            review_pt
            review_en
            category
            rating
    """

    aspect_categories = {
        # Product
        "product_quality": "product",
        "product_condition_damage": "product",
        "product_color_accuracy": "product",
        "product_appearance": "product",

        # Seller
        "product_completeness": "seller",
        "product_description_accuracy": "seller",
        "wrong_item_shipped": "seller",
        "price": "seller",
        "seller_contact": "seller",
        "seller_service": "seller",

        # Delivery
        "packaging": "delivery",
        "delivery_timing": "delivery",
        "delivery_non_receipt": "delivery",
    }

    attitude_sign = {
        "positive": 1,
        "neutral": 0,
        "negative": -1,
    }

    df = aggregated_df.copy()

    # Exclude aspects that are not part of the three-category
    # rating system.
    df = df[
        ~df["aspect"].isin(
            ["overall_satisfaction", "others"]
        )
    ].copy()

    # Map specific aspects to the three categories.
    df["category"] = df["aspect"].map(aspect_categories)

    # This should now identify genuinely unmapped aspects.
    if df["category"].isna().any():
        unmapped = (
            df.loc[df["category"].isna(), "aspect"]
            .drop_duplicates()
            .tolist()
        )

        raise ValueError(
            f"Unmapped aspects: {unmapped}"
        )

    # Convert attitude into direction.
    df["attitude_sign"] = df["attitude"].map(attitude_sign)

    if df["attitude_sign"].isna().any():
        invalid = (
            df.loc[df["attitude_sign"].isna(), "attitude"]
            .drop_duplicates()
            .tolist()
        )

        raise ValueError(
            f"Unknown attitudes: {invalid}"
        )

    # Calculate the score of each specific aspect.
    df["aspect_score"] = (
        3
        + df["attitude_sign"]
        * df["weight"]
    ).clip(1, 5)

    # Average aspect scores within each review and category.
    score_df = (
        df.groupby(
            ["review_pt", "review_en", "category"],
            dropna=False,
            as_index=False,
        )["aspect_score"]
        .mean()
        .rename(columns={"aspect_score": "score"})
    )

    return score_df