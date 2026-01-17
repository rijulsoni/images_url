# Product Image Search API

A FastAPI-based service that searches for product images using Google Custom Search API based on a product list provided in a CSV file.

## Features

- **Batch Search**: Upload a CSV file containing product names and receive image results.
- **JSON Response**: Get search results in JSON format.
- **CSV Download**: Get search results as a downloadable CSV file.
- **Scoring Logic**: Intelligent scoring system to find the most relevant product images with white backgrounds.

## Prerequisites

- Python 3.8+
- Google Custom Search API Key
- Google Custom Search Engine ID (CSE ID)

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configuration**:
   Open `search_service.py` and configure your Google API credentials:
   ```python
   GOOGLE_API_KEY = "YOUR_GOOGLE_API_KEY"
   CSE_ID = "YOUR_CSE_ID"
   ```

3. **Run the Application**:
   ```bash
   uvicorn main:app --reload
   ```

## API Endpoints

### 1. Root
- **URL**: `/`
- **Method**: `GET`
- **Description**: Welcome message and documentation link.

### 2. Search Images (JSON)
- **URL**: `/search-images`
- **Method**: `POST`
- **Request**: Multi-part form data with a `.csv` file.
- **CSV Format**: Should ideally have a column named `Product Name`.
- **Response**: JSON containing the best image URL and a list of candidates for each product.

### 3. Search Images (Download)
- **URL**: `/search-images-download`
- **Method**: `POST`
- **Request**: Multi-part form data with a `.csv` file.
- **Response**: A downloadable CSV file with the search results.

## Interactive Documentation

Once the server is running, you can access the interactive API documentation at:
- Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- ReDoc: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

## Logging

The application provides detailed logs for debugging and tracking search progress in the console.
# images_url
