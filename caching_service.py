import json
import logging
from typing import Optional, List, Any
from database import image_cache_collection

logger = logging.getLogger(__name__)

async def get_cached_images(product_name: str, prefix: str = "img_search") -> Optional[List[Any]]:
    """
    Check MongoDB for cached image results.
    """
    try:
        # Check MongoDB
        db_data = await image_cache_collection.find_one({
            "product_name": product_name.lower().strip(),
            "prefix": prefix
        })
        if db_data:
            logger.info(f"📂 Cache hit (MongoDB) for: {product_name} ({prefix})")
            return db_data.get("results")
            
    except Exception as e:
        logger.error(f"Error checking cache for {product_name}: {e}")
    
    return None

async def save_cached_images(product_name: str, results: List[Any], prefix: str = "img_search"):
    """
    Save search results to MongoDB.
    """
    if not results:
        return

    normalized_name = product_name.lower().strip()

    try:
        # Save to MongoDB
        await image_cache_collection.update_one(
            {"product_name": normalized_name, "prefix": prefix},
            {"$set": {"results": results, "product_name": normalized_name, "prefix": prefix}},
            upsert=True
        )
        logger.info(f"💾 Results saved to MongoDB for: {product_name} ({prefix})")
    except Exception as e:
        logger.error(f"Error saving cache for {product_name}: {e}")
