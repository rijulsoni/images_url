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

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import List, Optional
import pandas as pd
import io
import os
import re
import json
import time
from search_service import process_products_csv
from scraper_service import UndetectedScraper
from ai_mapper import detect_columns_with_ai


app = FastAPI(
    title="E-commerce Scraping & Product Image Search API",
    description="API to scrape e-commerce sites and search for product images",
    version="2.0.0"
)

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
        logger.info(f"df is here {df}")
        logger.info(f"Processing {len(df)} products from CSV")
        # Process products
        logger.info(f"processing products {process_products_csv}")
        results_df = process_products_csv(df)
        
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
        results_df = process_products_csv(df)
        
        # Save to a temporary CSV
        output_file = "output_results.csv"
        results_df.to_csv(output_file, index=False)
        
        logger.info(f"Results saved to {output_file}, initiating download")
        return FileResponse(path=output_file, filename="product_images.csv", media_type="text/csv")

    except Exception as e:
        logger.error(f"Error processing search-images-download: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

