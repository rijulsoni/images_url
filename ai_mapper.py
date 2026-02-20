import json
import logging
import os
import re

# Load .env file automatically (requires: pip install python-dotenv)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on env var being set in shell

import anthropic

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    """Lazily create the Anthropic client so a missing key doesn't crash startup."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


# ---------------------------------------------------------------
# Heuristic fallback — no AI required
# ---------------------------------------------------------------
def _detect_columns_heuristic(df):
    """
    Rule-based column detection used when the AI call is unavailable.
    Inspects column names and sample values to find the four target columns.
    """
    cols = list(df.columns)
    result = {"product_name": None, "price": None, "image_url": None, "booker_id": None}

    for col in cols:
        cl = col.lower()
        sample_vals = df[col].dropna().astype(str).head(10).tolist()
        sample_str = " ".join(sample_vals).lower()

        # --- Image URL: collect candidates, pick best after loop ---

    # Score all columns to find the real image URL column
    if result["image_url"] is None:
        best_img_col, best_img_score = None, -1
        claimed = {result["booker_id"], result["price"]}
        for col in cols:
            if col in claimed:
                continue
            cl = col.lower()
            sample_vals = df[col].dropna().astype(str).head(10).tolist()
            if not sample_vals:
                continue

            url_count = sum(1 for v in sample_vals if v.startswith("http"))
            if url_count < len(sample_vals) * 0.5:
                continue  # not a URL column at all

            score = 0

            # Column name hints
            if any(kw in cl for kw in ["image", "img", "photo", "picture", "thumbnail"]):
                score += 15
            if any(kw in cl for kw in ["url", "link", "src"]):
                score += 5

            # Strongly prefer URLs that contain image extensions
            img_ext_count = sum(
                1 for v in sample_vals
                if re.search(r'\.(jpg|jpeg|png|webp|gif)', v, re.IGNORECASE)
            )
            score += img_ext_count * 10

            # Prefer URLs from known image CDN patterns
            cdn_count = sum(
                1 for v in sample_vals
                if re.search(r'(bbimages|/images?/|media\.|cdn\.|static\.|assets\.)', v, re.IGNORECASE)
            )
            score += cdn_count * 8

            # Penalise search/product-page links (not actual images)
            search_count = sum(
                1 for v in sample_vals
                if re.search(r'(search\?|product-search|keywords=|/products?/[^/]*$)', v, re.IGNORECASE)
            )
            score -= search_count * 10

            if score > best_img_score:
                best_img_score = score
                best_img_col = col

        result["image_url"] = best_img_col



        # --- Price (RRP) ---
        if result["price"] is None:
            if any(kw in cl for kw in ["rrp", "price", "cost", "retail"]):
                result["price"] = col
            elif re.search(r'rrp\s*£?\d', sample_str):
                result["price"] = col

        # --- Booker ID: collect candidates, pick best after loop ---

    # Score all columns to find the real Booker ID column
    if result["booker_id"] is None:
        best_id_col, best_id_score = None, -1
        claimed = {result["image_url"], result["price"]}
        for col in cols:
            if col in claimed:
                continue
            cl = col.lower()
            sample_vals = df[col].dropna().astype(str).head(10).tolist()
            if not sample_vals:
                continue

            # Normalise float-formatted integers: "287776.0" → "287776"
            norm_vals = [re.sub(r'\.0+$', '', v.strip()) for v in sample_vals]

            # Must all be purely numeric (after normalisation)
            if not all(re.fullmatch(r'\d+', v) for v in norm_vals if v):
                continue

            digit_lengths = [len(v) for v in norm_vals if v]
            if not digit_lengths:
                continue
            avg_len = sum(digit_lengths) / len(digit_lengths)

            # Must be in 5–8 digit range on average
            if not (4.5 < avg_len < 8.5):
                continue

            score = 0

            # Keyword match in column name
            if any(kw in cl for kw in [
                "booker", "product_id", "productid", "merchant",
                "item_id", "itemid", "sku", "code", "ref"
            ]):
                score += 15

            # Prefer shorter IDs — Booker IDs are typically 5–6 digits
            # 8-digit values (web scrape IDs) get a strong penalty
            if avg_len <= 6:
                score += 10
            elif avg_len >= 8:
                score -= 10

            # Prefer consistent digit length (Booker IDs don't vary wildly)
            if digit_lengths:
                variance = max(digit_lengths) - min(digit_lengths)
                score -= variance * 2

            if score > best_id_score:
                best_id_score = score
                best_id_col = col

        result["booker_id"] = best_id_col


    # Pick the best product name column by scoring all candidates
    if result["product_name"] is None:
        best_col, best_score = None, -1
        claimed = {result["booker_id"], result["price"], result["image_url"]}
        for col in cols:
            if col in claimed:
                continue
            cl = col.lower()
            sample_vals = df[col].dropna().astype(str).head(10).tolist()
            if not sample_vals:
                continue

            score = 0

            # Column name keywords
            if any(kw in cl for kw in ["name", "product", "title", "description", "desc", "item"]):
                score += 10

            # Skip columns whose values look like URLs
            if sum(1 for v in sample_vals if v.startswith("http")) >= len(sample_vals) * 0.5:
                continue

            # Skip purely numeric / ID-like values (e.g. "1771504224-1")
            if all(re.fullmatch(r'[\d\-\.]+', v.strip()) for v in sample_vals if v.strip()):
                continue

            # Penalise index-like patterns (digits + hyphen + digit)
            if all(re.fullmatch(r'\d+[-_]\d+', v.strip()) for v in sample_vals if v.strip()):
                score -= 20

            # Reward multi-word values (real product names have spaces)
            avg_words = sum(len(v.split()) for v in sample_vals) / len(sample_vals)
            score += avg_words * 3

            # Reward longer average length
            avg_len = sum(len(v) for v in sample_vals) / len(sample_vals)
            score += avg_len * 0.5

            if score > best_score:
                best_score = score
                best_col = col

        result["product_name"] = best_col

    # Absolute last resort
    if result["product_name"] is None:
        text_cols = [c for c in cols if df[c].dtype == object]
        if text_cols:
            result["product_name"] = text_cols[0]
    if result["price"] is None:
        for col in cols:
            samples = df[col].dropna().astype(str).head(10).tolist()
            if any(re.search(r'rrp', s, re.I) for s in samples):
                result["price"] = col
                break
    if result["image_url"] is None:
        for col in cols:
            samples = df[col].dropna().astype(str).head(5).tolist()
            if any(s.startswith("http") for s in samples):
                result["image_url"] = col
                break

    logger.info(f"Heuristic column mapping: {result}")
    return result


# ---------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------
def detect_columns_with_ai(df):
    """
    Use Claude to detect product name, price, image URL, and Booker ID columns.
    Falls back to heuristic detection if the AI call fails (quota, network, etc.).
    """
    sample = df.head(20).to_dict()

    prompt = f"""
    You are a grocery CSV extraction assistant.

    Identify from this dataset:

    1. Product Name column (text like Pepsi Max 2L Bottle)
    2. Price column containing RRP (e.g. RRP £2.99)
    3. Image URL column (http link ending with jpg/png/webp)
    4. Booker Product ID column 
       (numeric merchant code like 299374)

    Booker ID rules:
    - Mostly numeric
    - 5 to 8 digits
    - NOT barcode (EAN usually 12-14 digits)

    Return JSON only:

    {{
      "product_name": "column_name",
      "price": "column_name",
      "image_url": "column_name",
      "booker_id": "column_name"
    }}

    CSV SAMPLE:
    {sample}
    """

    try:
        response = _get_client().messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.content[0].text.strip()

        # Strip markdown code fences if present (e.g. ```json ... ```)
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        result = json.loads(raw.strip())
        logger.info(f"Claude column mapping: {result}")
        return result

    except Exception as e:
        logger.warning(f"AI column detection failed ({e}). Using heuristic fallback.")
        return _detect_columns_heuristic(df)
