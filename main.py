import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ],
    force=True
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict
import pandas as pd
import io
import os
import re
import json
import time
import urllib.parse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from search_service import process_products_csv
from scraper_service import UndetectedScraper
from ai_mapper import detect_columns_with_ai
from caching_service import get_cached_images, save_cached_images


app = FastAPI(
    title="E-commerce Scraping & Product Image Search API",
    description="API to scrape e-commerce sites and search for product images",
    version="2.0.0"
)

executor = ThreadPoolExecutor(max_workers=10)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Pydantic models for request/response
class ScrapeRequest(BaseModel):
    url: str
    headless: bool = False

class ScrapeResponse(BaseModel):
    success: bool
    site_name: str
    products_count: int
    products: List[dict]
    csv_file: Optional[str] = None

class BatchScrapeRequest(BaseModel):
    sites: Optional[List[str]] = None  # List of site keys from config, or None for all
    headless: bool = False

class SiteConfigResponse(BaseModel):
    sites: dict

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the frontend configuration manager"""
    logger.info("Root endpoint accessed - serving frontend")
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api")
async def api_info():
    """API information endpoint"""
    logger.info("API info endpoint accessed")
    return {
        "message": "Welcome to the E-commerce Scraping & Product Image Search API",
        "endpoints": {
            "scraping": {
                "/scrape": "POST - Scrape a single URL",
                "/scrape-batch": "POST - Scrape multiple sites from config",
                "/sites": "GET - List available site configurations",
                "/sites/config": "POST - Update site configuration"
            },
            "image_search": {
                "/search-images": "POST - Search for product images from CSV",
                "/search-images-download": "POST - Search and download results as CSV"
            }
        },
        "docs": "/docs",
        "frontend": "/"
    }

# ==================== SCRAPING ENDPOINTS ====================

@app.post("/scrape", response_model=ScrapeResponse)
async def scrape_single_site(request: ScrapeRequest):
    """
    Scrape a single e-commerce site URL
    
    - **url**: The URL to scrape
    - **headless**: Run browser in headless mode (default: False)
    """
    logger.info(f"Received scrape request for URL: {request.url}")
    
    try:
        scraper = UndetectedScraper()
        products = scraper.scrape_site(request.url, headless=request.headless)
        
        site_type = scraper.detect_site(request.url)
        site_name = scraper.configs.get(site_type, {}).get('name', 'Unknown Site')
        
        # Save to CSV
        csv_filename = scraper.save_to_csv(products, site_name=site_name)
        
        logger.info(f"Successfully scraped {len(products)} products from {site_name}")
        
        return ScrapeResponse(
            success=True,
            site_name=site_name,
            products_count=len(products),
            products=products,
            csv_file=csv_filename
        )
        
    except Exception as e:
        logger.error(f"Error scraping site: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")

@app.post("/scrape-batch")
async def scrape_batch_sites(request: BatchScrapeRequest):
    """
    Scrape multiple sites from the configuration file
    
    - **sites**: List of site keys to scrape (e.g., ["deliveroo", "justeat"]). If None, scrapes all sites.
    - **headless**: Run browser in headless mode (default: False)
    """
    logger.info(f"Received batch scrape request for sites: {request.sites}")
    
    try:
        scraper = UndetectedScraper()
        results = []
        
        # Determine which sites to scrape
        sites_to_scrape = request.sites if request.sites else [
            key for key in scraper.configs.keys() if key != 'generic'
        ]
        
        for site_key in sites_to_scrape:
            if site_key not in scraper.configs:
                logger.warning(f"Site '{site_key}' not found in config, skipping...")
                continue
                
            site_config = scraper.configs[site_key]
            url = site_config.get('url')
            
            if not url:
                logger.warning(f"No URL found for {site_key}, skipping...")
                continue
            
            logger.info(f"\n{'='*60}")
            logger.info(f"Starting scrape: {site_config['name']}")
            logger.info(f"URL: {url}")
            logger.info(f"{'='*60}")
            
            try:
                products = scraper.scrape_site(url, headless=request.headless)
                csv_filename = scraper.save_to_csv(products, site_name=site_config['name'])
                
                results.append({
                    "site_key": site_key,
                    "site_name": site_config['name'],
                    "success": True,
                    "products_count": len(products),
                    "csv_file": csv_filename,
                    "products": products
                })
                
                logger.info(f"✅ Scraped {len(products)} products from {site_config['name']}")
                
            except Exception as e:
                logger.error(f"❌ Error scraping {site_key}: {str(e)}")
                results.append({
                    "site_key": site_key,
                    "site_name": site_config.get('name', site_key),
                    "success": False,
                    "error": str(e),
                    "products_count": 0
                })
            
            time.sleep(5)  # Delay between sites
        
        total_products = sum(r.get('products_count', 0) for r in results)
        logger.info(f"\n🎉 Batch scraping complete. Total products: {total_products}")
        
        return JSONResponse(content={
            "success": True,
            "total_sites": len(results),
            "total_products": total_products,
            "results": results
        })
        
    except Exception as e:
        logger.error(f"Error in batch scraping: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Batch scraping failed: {str(e)}")

@app.get("/sites", response_model=SiteConfigResponse)
async def get_site_configs():
    """
    Get all available site configurations
    """
    logger.info("Fetching site configurations")
    
    try:
        with open('site_config.json', 'r') as f:
            configs = json.load(f)
        
        # Remove sensitive data and simplify for display
        simplified_configs = {}
        for key, config in configs.items():
            simplified_configs[key] = {
                "name": config.get("name", "Unknown"),
                "url": config.get("url", "N/A"),
                "requires_postcode": config.get("requires_postcode", False),
                "scroll_passes": config.get("scroll_passes", 15)
            }
        
        return SiteConfigResponse(sites=simplified_configs)
        
    except Exception as e:
        logger.error(f"Error reading site config: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read configuration: {str(e)}")

@app.post("/sites/config")
async def update_site_config(site_key: str, config: dict):
    """
    Update configuration for a specific site
    
    - **site_key**: The site identifier (e.g., "deliveroo", "justeat")
    - **config**: The new configuration object
    """
    logger.info(f"Updating config for site: {site_key}")
    
    try:
        with open('site_config.json', 'r') as f:
            configs = json.load(f)
        
        configs[site_key] = config
        
        with open('site_config.json', 'w') as f:
            json.dump(configs, f, indent=2)
        
        logger.info(f"Successfully updated config for {site_key}")
        return JSONResponse(content={
            "success": True,
            "message": f"Configuration for '{site_key}' updated successfully"
        })
        
    except Exception as e:
        logger.error(f"Error updating site config: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update configuration: {str(e)}")

# ==================== CSV COLUMN DETECTION ENDPOINT ====================

def extract_rrp(text):
    """
    Extract numeric RRP price — ONLY when 'RRP' is explicitly present in the string.
    Handles:
      - "RRP £2.99" / "RRP 2.99" (price after RRP)
      - "£2.29 RRP Case of 12" (price before RRP with £)
      - "inc 1.11 RRP 18x330m" (decimal price before RRP, no £)
    Returns None for anything without an explicit RRP mention.
    """
    if pd.isna(text):
        return None
    s = str(text)

    # Must contain 'RRP' (case-insensitive) — strict gate
    if not re.search(r'RRP', s, re.IGNORECASE):
        return None

    # Pattern 1: price comes BEFORE "RRP" — e.g. "£2.29 RRP" or "1.11 RRP"
    m = re.search(r'£?\s*(\d+\.\d+)\s+RRP', s, re.IGNORECASE)
    if m:
        return m.group(1)

    # Pattern 2: price comes AFTER "RRP" — e.g. "RRP £2.99"
    # Only capture values that look like a real price (decimal, or integer ≥ £1 and < £500)
    m = re.search(r'RRP\s*£?\s*(\d+\.?\d*)', s, re.IGNORECASE)
    if m:
        candidate = m.group(1)
        try:
            val = float(candidate)
            # Exclude pack quantities masquerading as prices (e.g. "18" in "RRP 18x330ml")
            if '.' in candidate or (1 <= val < 500 and val >= 10):
                return candidate
        except ValueError:
            pass

    return None


# ==================== S3 IMAGE UPLOAD ====================

try:
    import boto3
    from botocore.exceptions import ClientError
    _boto3_available = True
except ImportError:
    _boto3_available = False
    logger.warning("boto3 not installed — S3 image upload disabled. Run: pip install boto3")

_s3_client = None

def _get_s3():
    """Lazily initialise the boto3 S3 client from env vars."""
    global _s3_client
    if not _boto3_available:
        raise RuntimeError("boto3 is not installed")
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            region_name=os.getenv("AWS_REGION", "eu-west-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
    return _s3_client

def upload_image_to_s3(booker_url: str) -> str:
    logger.info(f"Uploading image to S3333: {booker_url}")
    bucket = os.getenv("S3_BUCKET_NAME")
    region = os.getenv("AWS_REGION", "eu-west-1")

    try:
        parsed = urllib.parse.urlparse(booker_url)
        filename = parsed.path.lstrip("/").replace("/", "_")
        s3_key = f"booker-images/{filename}"

        s3 = _get_s3()
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "accept-language": "en-US,en;q=0.9",
            "priority": "u=0, i",
            "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
        }
        # Download image first so we know the content type
        import requests
        img_resp = requests.get(booker_url, headers=headers, timeout=20)
        logger.info(f"Image response: {img_resp} (status={img_resp.status_code})")
        if img_resp.status_code != 200:
            logger.warning(f"Failed to fetch image ({img_resp.status_code}): {booker_url}")
            return booker_url

        content_type = img_resp.headers.get("Content-Type", "image/jpeg")
        logger.info(f"Content type: {content_type}")
        # Include ContentType in presigned URL so signatures match
        presigned_url = s3.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': bucket,
                'Key': s3_key,
                'ContentType': content_type  # ✅ must match upload header
            },
            ExpiresIn=300
        )
        logger.info(f"Uploading image to S3 444: {presigned_url}")

        # ✅ Send the same Content-Type header during upload
        upload_resp = requests.put(
            presigned_url,
            data=img_resp.content,
            headers={"Content-Type": content_type}
        )

        if upload_resp.status_code == 200:
            return f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"

    except Exception as e:
        logger.warning(f"S3 upload failed: {e}")

    return booker_url
    
async def upload_parallel(urls):
   
    loop = asyncio.get_running_loop()
    logger.info(f"Uploadfrrfrfrf {len(urls)} images to S3")
    tasks = [
        loop.run_in_executor(
            executor,
            upload_image_to_s3,
            str(u)
        )
        for u in urls
        if pd.notna(u) and str(u).startswith("http")
    ]

    return await asyncio.gather(*tasks)

@app.post("/upload-csv/")
async def upload_csv(file: UploadFile = File(...)):
    """
    Upload a grocery CSV, auto-detect columns with AI, and download
    a cleaned CSV with: booker_id, product_name, price, image_url.
    """
    logger.info(f"Received upload-csv request for file: {file.filename}")

    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))

        if df.empty:
            raise HTTPException(status_code=400, detail="The uploaded CSV file is empty.")

        # 🔥 AI detects correct columns
        mapping = detect_columns_with_ai(df)
        name_col   = mapping["product_name"]
        price_col  = mapping["price"]
        image_col  = mapping["image_url"]
        booker_col = mapping["booker_id"]
        logger.info(f"Detected mapping: {mapping}")

        # Guard: make sure every column was detected
        missing = [k for k, v in mapping.items() if v is None]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Could not auto-detect columns: {missing}. "
                    f"CSV columns found: {list(df.columns)}. "
                    f"Please ensure the CSV has product name, price, image URL, and booker ID columns."
                )
            )

        logger.info(f"Price col samples:  {df[price_col].dropna().head(5).tolist()}")
        logger.info(f"Booker col samples: {df[booker_col].dropna().head(5).tolist()}")


        # Build clean output DataFrame
        new_df = pd.DataFrame()
        new_df["booker_id"]    = df[booker_col]
        new_df["product_name"] = df[name_col]
        new_df["price"]        = df[price_col].apply(extract_rrp)
        new_df["image_url"]    = df[image_col]

        total_before = len(new_df)

        # Remove rows with no price
        new_df = new_df.dropna(subset=["price"])
        logger.info(f"After price filter: {len(new_df)}/{total_before} rows remain")

        # Keep only valid Booker IDs (5–8 digits, not EAN barcodes)
        new_df = new_df[
            new_df["booker_id"].astype(str).str.strip().str.match(r'^\d{5,8}$')
        ]
        logger.info(f"After booker_id filter: {len(new_df)}/{total_before} rows remain")

        if new_df.empty:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"All rows were filtered out. "
                    f"Detected columns → name='{name_col}', price='{price_col}', "
                    f"image='{image_col}', booker_id='{booker_col}'. "
                    f"Check that the price column contains values like 'RRP £2.99' "
                    f"and booker_id is 5-8 digits."
                )
            )

        output_file = "processed_products.csv"
        new_df.to_csv(output_file, index=False)

        logger.info(f"Processed {len(new_df)} products, returning CSV")
        return FileResponse(
            output_file,
            media_type="text/csv",
            filename="processed_products.csv"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in upload-csv: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


# ==================== IMAGE SEARCH ENDPOINTS ====================

@app.post("/search-images")
async def search_images(file: UploadFile = File(...)):
    print("testing")
    logger.info(f"Received search-images request for file: {file.filename}")
    if not file.filename.endswith('.csv'):
        logger.warning(f"Invalid file type attempted: {file.filename}")
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a CSV file.")
    
    try:
        # Read the uploaded CSV
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
        
        if df.empty:
            logger.warning("Uploaded CSV file is empty")
            raise HTTPException(status_code=400, detail="The uploaded CSV file is empty.")
        
        logger.info(f"Processing {len(df)} products from CSV")
        # Process products
        results_df = await process_products_csv(df)
        
        # Convert result to dict to return as JSON
        results = results_df.to_dict(orient="records")
        
        logger.info("Successfully processed products")
        return JSONResponse(content={"results": results})

    except Exception as e:
        logger.error(f"Error processing search-images: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

@app.post("/search-images-download")
async def search_images_download(file: UploadFile = File(...)):
    logger.info(f"Received search-images-download request for file: {file.filename}")
    if not file.filename.endswith('.csv'):
        logger.warning(f"Invalid file type attempted: {file.filename}")
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a CSV file.")
    
    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
        
        logger.info(f"Processing {len(df)} products for download")
        results_df = await process_products_csv(df)
        
        # Save to a temporary CSV
        output_file = "output_results.csv"
        results_df.to_csv(output_file, index=False)
        
        logger.info(f"Results saved to {output_file}, initiating download")
        return FileResponse(path=output_file, filename="product_images.csv", media_type="text/csv")

    except Exception as e:
        logger.error(f"Error processing search-images-download: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


# ==================== FLASH CSV UPDATER ====================
# ==================== FLASH CSV UPDATER ====================

@app.post("/preview-flash-csv")
async def preview_flash_csv(
    flash_csv: UploadFile = File(...),
    booker_csv: UploadFile = File(...)
):
    """
    Step 1: Merge user Flash CSV with Booker CSV and return the preview data.
    """
    try:
        flash_df  = pd.read_csv(io.BytesIO(await flash_csv.read()), dtype=str)
        booker_df = pd.read_csv(io.BytesIO(await booker_csv.read()), dtype=str)

        flash_df.columns  = flash_df.columns.str.strip()
        booker_df.columns = booker_df.columns.str.strip()

        flash_df["SKU"]        = flash_df["SKU"].astype(str).str.strip()
        booker_df["booker_id"] = booker_df["booker_id"].astype(str).str.strip()

        # Merge
        merged = flash_df.merge(
            booker_df[["booker_id", "product_name", "price", "image_url"]],
            left_on="SKU",
            right_on="booker_id",
            how="left"
        )
        
        # Build JSON response
        # We send back merged data as csv_data, but ALL booker rows as preview_items
        return JSONResponse(content={
            "csv_data": merged.fillna("").to_dict(orient="records"),
            "preview_items": booker_df.fillna("").to_dict(orient="records")
        })

    except Exception as e:
        logger.error(f"Error in preview-flash-csv: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/finalize-flash-csv")
async def finalize_flash_csv(
    flash_csv: UploadFile = File(...),
    booker_csv: UploadFile = File(...),
    enhance_flags_str: str = Form(...)  # JSON string of booker_id -> bool
):
    """
    Step 2: Take user selections for enhancements, process all Booker images, upload to S3,
    and return the final merged CSV.
    """
    try:
        flash_df  = pd.read_csv(io.BytesIO(await flash_csv.read()), dtype=str)
        booker_df = pd.read_csv(io.BytesIO(await booker_csv.read()), dtype=str)

        flash_df.columns  = flash_df.columns.str.strip()
        booker_df.columns = booker_df.columns.str.strip()

        flash_df["SKU"]        = flash_df["SKU"].astype(str).str.strip()
        booker_df["booker_id"] = booker_df["booker_id"].astype(str).str.strip()

        # Parse enhance flags
        enhance_flags = json.loads(enhance_flags_str) if enhance_flags_str else {}

        logger.info(f"Processing Booker CSV with {len(booker_df)} total rows. {sum(enhance_flags.values())} to enhance.")

        # Gather unique URLs to upload to S3 from booker_df
        unique_bookers = booker_df[booker_df["booker_id"] != ""].drop_duplicates(subset=["booker_id"])
        
        urls_to_process = []
        for _, row in unique_bookers.iterrows():
            b_id = row["booker_id"]
            url = row["image_url"]
            if url and str(url).startswith("http"):
                urls_to_process.append((b_id, url, enhance_flags.get(str(b_id), False)))

        # Process uploads/enhancements
        async def process_image(b_id, url, should_enhance):
            if should_enhance:
                logger.info(f"Enhancing image for booker_id {b_id}: {url}")
                try:
                    req = EnhanceImageRequest(image_url=url)
                    res = await enhance_image(req)
                    if res.get("success"):
                        return b_id, res.get("enhanced_url")
                except Exception as e:
                    logger.error(f"Failed to enhance {url}: {e}")
            
            # If not enhancing, or enhancement failed, upload the original to S3
            logger.info(f"Uploading original to S3 for booker_id {b_id}: {url}")
            loop = asyncio.get_running_loop()
            s3_url = await loop.run_in_executor(executor, upload_image_to_s3, str(url))
            return b_id, s3_url

        tasks = [process_image(b_id, url, enhance) for b_id, url, enhance in urls_to_process]
        results = await asyncio.gather(*tasks)

        # Map back new S3 URLs into booker_df
        s3_mapping = {b_id: final_url for b_id, final_url in results if final_url}
        
        def update_url(row):
            b_id = row["booker_id"]
            return s3_mapping.get(b_id, row["image_url"]) if b_id else row["image_url"]

        booker_df["image_url"] = booker_df.apply(update_url, axis=1)

        logger.info("Booker images uploaded to S3 successfully")

        # Merge Phase
        merged = flash_df.merge(
            booker_df[["booker_id", "price", "image_url"]],
            left_on="SKU",
            right_on="booker_id",
            how="left"
        )
        
        # Final merge mappings
        merged.replace("", pd.NA, inplace=True)
        merged["Product Price*"] = merged["price"].combine_first(merged["Product Price*"])
        merged["Product Image Url"] = merged["image_url"].combine_first(merged["Product Image Url"])

        # Drop the temporary booker columns
        cols_to_drop = [c for c in ["booker_id", "price", "image_url"] if c in merged.columns]
        merged.drop(columns=cols_to_drop, inplace=True)
        
        merged.fillna("", inplace=True)

        logger.info("Merge complete — Flash now contains S3 image links")

        buf = io.BytesIO()
        merged.to_csv(buf, index=False)
        buf.seek(0)

        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=updated_flash.csv"}
        )

    except Exception as e:
        logger.error(f"Error in finalize-flash-csv: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== SERPAPI IMAGE URL UPDATER ====================

class FinalizeSelection(BaseModel):
    csv_data: List[dict]
    selections: Dict[int, str]  # index -> selected_url
    enhance_flags: Optional[Dict[int, bool]] = None # index -> should_enhance

async def _serpapi_image_candidates(product_name: str, max_candidates: int = 10) -> List[Dict[str, str]]:
    """
    Search Google Images via Serper.dev and return top candidates.
    Each candidate has: thumbnail, original
    """
    import requests as req

    api_key = os.getenv("SERPER_API_KEY", "ae93ba8c6bcba3f9978cea00e0499fa86edd7979")
    if not api_key:
        logger.warning("SERPER_API_KEY not set — skipping image search")
        return []

    try:
        url = "https://google.serper.dev/images"
        payload = {"q": product_name,  "gl": "gb"}
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }

        # requests.post is blocking, so run in thread
        resp = await asyncio.to_thread(req.post, url, headers=headers, json=payload, timeout=15)
        data = resp.json()

        logger.info(f"Serper response keys: {list(data.keys())} for '{product_name}'")

        images = data.get("images", [])
        logger.info(f"Serper returned {len(images)} images for '{product_name}'")

        candidates = []
        
        for img in images[:max_candidates]:
            original = img.get("imageUrl", "")
            thumbnail = img.get("thumbnailUrl", original)
            if original and original.startswith("http"):
                candidates.append({
                    "original": original,
                    "thumbnail": thumbnail,
                })

        return candidates
    except Exception as e:
        logger.warning(f"Serper image search failed for '{product_name}': {e}")
    return []


@app.post("/get-image-candidates")
async def get_image_candidates(file: UploadFile = File(...)):
    """
    Upload CSV and fetch top 10 image candidates for each product.
    Returns: { "csv_data": [...], "candidates": [[cand1, cand2, ...], ...] }
    """

    logger.info(f"get-image-candidates: received '{file.filename}'")

    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    try:
        contents = await file.read()
        try:
            df = pd.read_csv(io.BytesIO(contents))
        except UnicodeDecodeError:
            df = pd.read_csv(io.BytesIO(contents), encoding="latin1")

        if df.empty:
            raise HTTPException(status_code=400, detail="The uploaded CSV file is empty.")

        # ── Detect product-name column ──────────────────────────────
        product_col = None
        try:
            detected = detect_columns_with_ai(df)
            product_col = detected.get("product_name")
        except Exception as ai_err:
            logger.warning(f"AI column detection failed: {ai_err}")

        if not product_col or product_col not in df.columns:
            for col in df.columns:
                if "product" in col.lower() and "name" in col.lower():
                    product_col = col
                    break

            if not product_col:
                product_col = df.columns[0]

        # ── Direct SerpAPI Lookups (No Cache / No DB) ───────────────
        product_names = df[product_col].fillna("").astype(str).tolist()
        logger.info(f"Product names 11: {product_names}")
        tasks = [
            _serpapi_image_candidates(name)
            for name in product_names
        ]

        all_candidates = await asyncio.gather(*tasks)
        logger.info(f"All candidates 11: {all_candidates}")

        return {
            "csv_data": df.fillna("").to_dict(orient="records"),
            "candidates": all_candidates,
            "product_col": product_col
        }

    except Exception as e:
        logger.error(f"Error in get-image-candidates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# @app.post("/get-image-candidates")
# async def get_image_candidates(file: UploadFile = File(...)):
#     """
#     Step 1: Upload CSV and fetch top 10 image candidates for each product.
#     Returns: { "csv_data": [...], "candidates": [[cand1, cand2, ...], ...] }
#     """
#     logger.info(f"get-image-candidates: received '{file.filename}'")

#     if not file.filename.endswith(".csv"):
#         raise HTTPException(status_code=400, detail="Please upload a CSV file.")

#     try:
#         contents = await file.read()
#         df = pd.read_csv(io.BytesIO(contents))

#         if df.empty:
#             raise HTTPException(status_code=400, detail="The uploaded CSV file is empty.")

#         # ── Detect product-name column ──────────────────────────────────────
#         product_col = None
#         try:
#             detected = detect_columns_with_ai(df)
#             product_col = detected.get("product_name")
#         except Exception as ai_err:
#             logger.warning(f"AI column detection failed: {ai_err}")

#         if not product_col or product_col not in df.columns:
#             for col in df.columns:
#                 if "product" in col.lower() and "name" in col.lower():
#                     product_col = col
#                     break
#             if not product_col:
#                 product_col = df.columns[0]

#         # ── Check Cache/DB first ──
#         product_names = df[product_col].fillna("").astype(str).tolist()
#         all_candidates = []
#         to_search = []
#         search_indices = []

#         for idx, name in enumerate(product_names):
#             cached = await get_cached_images(name, prefix="serpapi")
#             if cached:
#                 all_candidates.append(cached)
#             else:
#                 all_candidates.append(None) # Placeholder
#                 to_search.append(name)
#                 search_indices.append(idx)

#         # ── Parallel SerpAPI lookups for non-cached ──
#         if to_search:
#             # Call the async function directly
#             new_tasks = [
#                 _serpapi_image_candidates(name)
#                 for name in to_search
#             ]
#             fresh_results = await asyncio.gather(*new_tasks)
            
#             for idx, result in zip(search_indices, fresh_results):
#                 all_candidates[idx] = result

#         return {
#             "csv_data": df.fillna("").to_dict(orient="records"),
#             "candidates": all_candidates,
#             "product_col": product_col
#         }

#     except Exception as e:
#         logger.error(f"Error in get-image-candidates: {e}", exc_info=True)
#         raise HTTPException(status_code=500, detail=str(e))


@app.post("/finalize-csv-interactive")
async def finalize_csv_interactive(data: FinalizeSelection):
    """
    Step 2: Merge user selections into the CSV data, process enhancements if flagged,
    and return the file for download.
    """
    try:
        df = pd.DataFrame(data.csv_data)
        
        # Detect the actual image column name in the CSV
        image_col = None
        for col in df.columns:
            if col.lower().replace(" ", "").replace("_", "") in ("productimageurl", "imageurl", "image_url"):
                image_col = col
                break
        if not image_col:
            image_col = "Product Image Url"
            df[image_col] = ""

        enhance_flags = data.enhance_flags or {}

        # Update the image column based on user selections
        for idx_str, selected_url in data.selections.items():
            idx = int(idx_str)
            if idx < len(df):
                final_url = selected_url
                
                # Check if this image needs enhancement
                if enhance_flags.get(idx_str, False) or enhance_flags.get(idx, False):
                    logger.info(f"Enhancement requested for index {idx} with URL {selected_url}")
                    try:
                        # Call the enhance function logic directly
                        req = EnhanceImageRequest(image_url=selected_url)
                        enhance_result = await enhance_image(req)
                        if enhance_result.get("success"):
                            final_url = enhance_result.get("enhanced_url", selected_url)
                    except Exception as e:
                        logger.error(f"Failed to enhance image at index {idx}: {e}")
                        # Fallback to original if enhancement fails
                        final_url = selected_url

                df.at[idx, image_col] = final_url

        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=updated_products.csv"},
        )
    except Exception as e:
        logger.error(f"Error in finalize-csv-interactive: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class EnhanceImageRequest(BaseModel):
    image_url: str

@app.post("/enhance-image")
async def enhance_image(request: EnhanceImageRequest):
    """
    Download the image from the given URL, enhance it using Gemini API,
    and upload the enhanced version to S3. Return the new S3 URL.
    """
    import requests
    from io import BytesIO

    logger.info(f"Enhance image requested for URL: {request.image_url}")

    try:
        api_key = os.getenv("GEMINI_API_KEY")

        # --- Add this temporary debug line ---
        if api_key:
            logger.info(f"DEBUG: Key length is {len(api_key)}. Starts with: '{api_key[:5]}', ends with: '{api_key[-3:]}'")
        if not api_key:
            logger.warning("GEMINI_API_KEY is missing from environment variables.")
            # Fallback or error based on your preference. Returning placeholder for now.
            return {"success": True, "enhanced_url": request.image_url, "message": "API key missing. Returning original."}

        # Download the original image
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
        }
        resp = requests.get(request.image_url, headers=headers, timeout=20)
        
        if resp.status_code != 200:
            logger.warning(f"Failed to fetch image for enhancement ({resp.status_code}): {request.image_url}")
            raise HTTPException(status_code=400, detail=f"Failed to download image from URL. Status Code: {resp.status_code}")

        # Get the original image bytes directly
        image_bytes = resp.content
        logger.info(f"Image bytes: {image_bytes}")
        mime_type = resp.headers.get("Content-Type", "image/jpeg")

        logger.info("Calling Gemini API to enhance image...")
        
        try:
            from google import genai
            from google.genai import types
        except ModuleNotFoundError as import_error:
            logger.error("google-genai SDK is not installed. Install it with: pip install google-genai")
            raise HTTPException(
                status_code=500,
                detail="google-genai SDK is not installed. Run 'pip install google-genai'.",
            ) from import_error
        import urllib.parse
        import time
        client = genai.Client(api_key=api_key)
        
        model = "gemini-2.5-flash-image"
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    types.Part.from_text(text="Enhance this image: significantly improve quality, make it high resolution, sharp, and vibrant. Follow the original image closely. Output only the enhanced image."),
                ],
            ),
        ]
        generate_content_config = types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        )

        generated_image_bytes = None
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.parts is None:
                continue
            if chunk.parts[0].inline_data and chunk.parts[0].inline_data.data:
                generated_image_bytes = chunk.parts[0].inline_data.data
                break
        
        if not generated_image_bytes:
            logger.error("Gemini API did not return an image.")
            raise Exception("Gemini API did not return an image.")

        # Save to buffer for S3
        output_buffer = BytesIO(generated_image_bytes)
        
        # --- Upload to S3 ---
        bucket = os.getenv("S3_BUCKET_NAME")
        region = os.getenv("AWS_REGION", "eu-west-1")
        
        parsed = urllib.parse.urlparse(request.image_url)
        original_filename = os.path.basename(parsed.path)
        if not original_filename:
            original_filename = "image"
        
        name, _ = os.path.splitext(original_filename)
        timestamp = int(time.time())
        filename = f"{name}_enhanced_{timestamp}.jpg"
        s3_key = f"enhanced-images/{filename}"

        s3 = _get_s3()
        content_type = "image/jpeg"
        
        presigned_url = s3.generate_presigned_url(
            'put_object',
            Params={'Bucket': bucket, 'Key': s3_key, 'ContentType': content_type},
            ExpiresIn=300
        )
        
        upload_resp = requests.put(
            presigned_url,
            data=output_buffer.getvalue(),
            headers={"Content-Type": content_type}
        )

        if upload_resp.status_code == 200:
            enhanced_url = f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"
            logger.info(f"Successfully enhanced and uploaded image to S3: {enhanced_url}")
            return {"success": True, "enhanced_url": enhanced_url}
        else:
            logger.error(f"Failed to upload enhanced image to S3: Status {upload_resp.status_code}")
            raise HTTPException(status_code=500, detail="Failed to upload enhanced image to S3")

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error in enhance_image: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
