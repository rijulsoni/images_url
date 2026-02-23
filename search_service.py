import requests
import asyncio
import pandas as pd
import logging
from typing import List, Dict
from ai_mapper import detect_columns_with_ai
from caching_service import get_cached_images, save_cached_images

# Configure logging for the service
logger = logging.getLogger(__name__)

# ===================== CONFIG =====================
GOOGLE_API_KEY = "AIzaSyCY__tOZOP2CUV9mtuAE8LPpTQztNKTshU"
CSE_ID = "338e839e30c8a4d21"

def is_multipack(product: str) -> bool:
    keywords = ["pack", "bundle", "combo", "set"]
    return any(k in product.lower() for k in keywords)

async def google_image_search(query: str, max_results: int = 15) -> List[Dict]:
    logger.info(f"Searching Google Images for: '{query}'")
    images = []
    start = 1

    while len(images) < max_results:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": GOOGLE_API_KEY,
            "cx": CSE_ID,
            "q": query,
            "searchType": "image",
            "num": min(10, max_results - len(images)),
            "start": start
        }

        try:
            # Use asyncio.to_thread for requests if not using httpx
            r_resp = await asyncio.to_thread(requests.get, url, params=params)
            r = r_resp.json()
            items = r.get("items", [])

            if not items:
                logger.debug(f"No more items found for query: {query}")
                break

            for item in items:
                images.append({
                    "image": item.get("link", ""),
                    "title": item.get("title", "").lower(),
                    "width": item.get("image", {}).get("width", 0),
                    "height": item.get("image", {}).get("height", 0)
                })

            logger.info(f"Found {len(items)} items in current page. Total so far: {len(images)}")
            start += 10
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Error during Google Image search: {e}")
            break

    return images

async def find_product_image(product: str, top_n: int = 5) -> List[str]:
    product_name = str(product).strip()
    logger.info(f"find product image {product_name}")
    
    # 1. Check Cache/DB first
    cached = await get_cached_images(product_name)
    if cached:
        return cached[:top_n]

    candidates = []
    multipack = is_multipack(product_name)

    query = f"{product_name} product packaging white background isolated"
    logger.info(f"Beginning search for product: '{product_name}' (Multipack: {multipack})")
    
    try:
        results = await google_image_search(query, max_results=15)
        scored_results = []
        product_keywords = set(product_name.lower().split())

        for r in results:
            url = r.get("image", "")
            title = r.get("title", "").lower()
            width = r.get("width", 0)
            height = r.get("height", 0)

            if not url.lower().endswith((".jpg", ".jpeg", ".png")):
                continue

            if width and height:
                if width < 400 or height < 400 or width > 2500 or height > 2500:
                    continue

            if not multipack and any(w in title for w in ["2 pack", "3 pack", "bundle", "multipack"]):
                continue

            # Scoring logic
            score = 0
            title_keywords = set(title.split())
            overlap = len(product_keywords.intersection(title_keywords))
            score += overlap * 10
            
            if url.lower().endswith(".png"):
                score += 5
            
            if width and height:
                if 800 <= width <= 1500 and 800 <= height <= 1500:
                    score += 5

            scored_results.append((score, url))

        if scored_results:
            scored_results.sort(key=lambda x: x[0], reverse=True)
            # Pick top_n unique URLs
            seen_urls = set()
            for score, url in scored_results:
                if url not in seen_urls:
                    candidates.append(url)
                    seen_urls.add(url)
                    if len(candidates) >= 10: # Store more than top_n for thorough caching
                        break
            
            # 2. Save to Cache/DB
            await save_cached_images(product_name, candidates)
            
            logger.info(f"Found {len(candidates)} candidates for '{product_name}'. Best score: {scored_results[0][0]}")
        else:
            logger.warning(f"No suitable images found for: '{product_name}'")

    except Exception as e:
        logger.error(f"Error searching for {product_name}: {e}")

    return candidates[:top_n]

async def process_products_csv(input_df: pd.DataFrame) -> pd.DataFrame:
    logger.info(f"Starting batch processing of {len(input_df)} products")
    results_data = []

    # Use AI to detect column names
    try:
        detected = detect_columns_with_ai(input_df)
        product_col = detected.get("product_name")
        logger.info(f"AI detected columns: {detected}")
    except Exception as e:
        logger.warning(f"AI column detection failed: {e}. Falling back to heuristics.")
        detected = {}
        product_col = None

    # Fallback heuristic if AI didn't return a valid column
    if not product_col or product_col not in input_df.columns:
        product_col = 'Product Name'
        if product_col not in input_df.columns:
            for col in input_df.columns:
                if 'product' in col.lower() and 'name' in col.lower():
                    product_col = col
                    break
            else:
                product_col = input_df.columns[0]
                logger.warning(f"Column 'Product Name' not found. Using '{product_col}' instead.")

    for i, product in enumerate(input_df[product_col], start=1):
        logger.info(f"Processing product {i}/{len(input_df)}: {product}")
        candidates = await find_product_image(product)
        
        results_data.append({
            "product": product,
            "image_url": candidates[0] if candidates else "",
            "candidates": candidates
        })
    
    logger.info("Batch processing complete")
    return pd.DataFrame(results_data)
