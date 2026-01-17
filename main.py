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
from fastapi.responses import JSONResponse, FileResponse
import pandas as pd
import io
import os
from search_service import process_products_csv

app = FastAPI(
    title="Product Image Search API",
    description="API to search for product images based on a CSV list",
    version="1.0.0"
)

@app.get("/")
async def root():
    logger.info("Root endpoint accessed")
    return {"message": "Welcome to the Product Image Search API. Use /docs for documentation."}

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
