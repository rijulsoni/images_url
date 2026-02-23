import asyncio
from database import check_connections, image_cache_collection
from caching_service import get_cached_images, save_cached_images

async def run_verification():
    print("--- 🔍 Starting MongoDB Persistence Verification ---")
    
    # 1. Connection Check
    await check_connections()
    
    # 2. Persistence Logic Check
    test_product = "Test Product MongoDB Only"
    test_results = ["http://example.com/mongo1.jpg", "http://example.com/mongo2.jpg"]
    
    print(f"\n🧪 Testing MongoDB Save for: {test_product}")
    await save_cached_images(test_product, test_results, prefix="test")
    
    print(f"🧪 Testing MongoDB Retrieval for: {test_product}")
    cached = await get_cached_images(test_product, prefix="test")
    
    if cached == test_results:
        print("✅ MongoDB Retrieval successful!")
    else:
        print(f"❌ MongoDB verification failed. Expected {test_results}, got {cached}")
    
    # 3. DB Persistence Check
    print("\n🧪 Re-verifying MongoDB record directly...")
    db_item = await image_cache_collection.find_one({"product_name": test_product.lower(), "prefix": "test"})
    if db_item and db_item.get("results") == test_results:
        print("✅ MongoDB document verified!")
    else:
        print("❌ MongoDB document check failed.")
        
    # Cleanup test data
    await image_cache_collection.delete_one({"product_name": test_product.lower(), "prefix": "test"})
    print("\n🧹 Cleanup complete.")
    print("\n--- 🏁 Verification Finished ---")

if __name__ == "__main__":
    asyncio.run(run_verification())
