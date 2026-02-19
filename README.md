# E-commerce Scraping & Product Image Search API

A comprehensive FastAPI-based service that provides:
1. **Web Scraping**: Scrape e-commerce sites using SeleniumBase with Cloudflare bypass
2. **Image Search**: Find product images using Google Custom Search API

## Features

### Web Scraping
- 🔓 **Cloudflare Bypass**: Uses SeleniumBase's undetected Chrome mode
- 🎯 **Multi-site Support**: Pre-configured for Deliveroo, Just Eat, Snappy Shopper
- 📍 **Postcode Handling**: Automatic postcode entry for location-based sites
- 🔄 **Incremental Scrolling**: Extracts products while scrolling for complete coverage
- 📊 **CSV Export**: Automatic CSV generation for scraped data
- ⚙️ **Configurable**: JSON-based site configuration for easy customization

### Image Search
- 🔍 **Google Image Search**: Powered by Google Custom Search API
- 🎨 **Smart Filtering**: Filters images by size, format, and relevance
- 📦 **Batch Processing**: Process multiple products from CSV files
- 📥 **CSV Export**: Download results as CSV

## Installation

### Prerequisites
- Python 3.8+
- Chrome/Chromium browser (for web scraping)

### Setup

1. **Clone the repository** (or navigate to the project directory)

2. **Create a virtual environment**:
   ```bash
   python -m venv .venv
   ```

3. **Activate the virtual environment**:
   - Windows:
     ```bash
     .venv\Scripts\activate
     ```
   - macOS/Linux:
     ```bash
     source .venv/bin/activate
     ```

4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Configure site settings** (optional):
   - Edit `site_config.json` to customize scraping behavior
   - Add new sites or modify existing configurations

## Running the API

Start the server:
```bash
uvicorn main:app --reload
```

The API will be available at:
- **Base URL**: http://localhost:8000
- **Interactive Docs**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc

## API Endpoints

### Web Scraping Endpoints

#### 1. Scrape Single Site
**POST** `/scrape`

Scrape a single e-commerce site URL.

**Request Body**:
```json
{
  "url": "https://deliveroo.co.uk/menu/london/chelsea/pizza-express-chelsea",
  "headless": false
}
```

**Response**:
```json
{
  "success": true,
  "site_name": "Deliveroo",
  "products_count": 45,
  "products": [
    {
      "name": "Margherita Pizza",
      "price": "£12.50",
      "image_url": "https://example.com/image.jpg"
    }
  ],
  "csv_file": "deliveroo_products.csv"
}
```

**Example using curl**:
```bash
curl -X POST "http://localhost:8000/scrape" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://deliveroo.co.uk/menu/london/chelsea/pizza-express-chelsea", "headless": false}'
```

#### 2. Batch Scrape Multiple Sites
**POST** `/scrape-batch`

Scrape multiple sites from the configuration file.

**Request Body**:
```json
{
  "sites": ["deliveroo", "justeat"],
  "headless": false
}
```

Leave `sites` as `null` to scrape all configured sites.

**Response**:
```json
{
  "success": true,
  "total_sites": 2,
  "total_products": 89,
  "results": [
    {
      "site_key": "deliveroo",
      "site_name": "Deliveroo",
      "success": true,
      "products_count": 45,
      "csv_file": "deliveroo_products.csv",
      "products": [...]
    }
  ]
}
```

#### 3. Get Site Configurations
**GET** `/sites`

Retrieve all available site configurations.

**Response**:
```json
{
  "sites": {
    "deliveroo": {
      "name": "Deliveroo",
      "url": "https://deliveroo.co.uk/...",
      "requires_postcode": true,
      "scroll_passes": 20
    }
  }
}
```

#### 4. Update Site Configuration
**POST** `/sites/config?site_key=deliveroo`

Update configuration for a specific site.

**Request Body**: Complete site configuration object

### Image Search Endpoints

#### 5. Search Product Images
**POST** `/search-images`

Upload a CSV file with product names and get image URLs.

**Request**: Multipart form data with CSV file
- CSV should have a column named "Product Name" (or similar)

**Response**:
```json
{
  "results": [
    {
      "product": "Coca Cola 330ml",
      "image_url": "https://example.com/coke.jpg",
      "candidates": ["url1", "url2", "url3"]
    }
  ]
}
```

#### 6. Search and Download CSV
**POST** `/search-images-download`

Same as above but returns a downloadable CSV file.

## Configuration

### Site Configuration (`site_config.json`)

Each site configuration includes:

```json
{
  "site_key": {
    "name": "Site Name",
    "url": "https://example.com",
    "requires_postcode": true,
    "postcode": "GL52 3DT",
    "scroll_passes": 20,
    "extraction": {
      "name": {
        "xpath": "XPath selector for product name",
        "filters": ["no_price", "min_length:3"]
      },
      "image": {
        "xpath": "XPath selector for image",
        "attribute": "src",
        "fallback_attribute": "data-src",
        "trim_after": [".jpg", ".jpeg"]
      }
    }
  }
}
```

**Available Filters**:
- `no_price`: Exclude text containing currency symbols
- `no_calories`: Exclude calorie information
- `no_digit_only`: Exclude purely numeric text
- `min_length:N`: Minimum text length
- `no_common_words`: Exclude common UI words

## Usage Examples

### Python Example

```python
import requests

# Scrape a single site
response = requests.post(
    "http://localhost:8000/scrape",
    json={
        "url": "https://deliveroo.co.uk/menu/london/chelsea/pizza-express-chelsea",
        "headless": False
    }
)

data = response.json()
print(f"Scraped {data['products_count']} products")
print(f"CSV saved to: {data['csv_file']}")

# Batch scrape
response = requests.post(
    "http://localhost:8000/scrape-batch",
    json={
        "sites": ["deliveroo", "justeat"],
        "headless": False
    }
)

data = response.json()
print(f"Total products: {data['total_products']}")
```

### JavaScript Example

```javascript
// Scrape a single site
const response = await fetch('http://localhost:8000/scrape', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    url: 'https://deliveroo.co.uk/menu/london/chelsea/pizza-express-chelsea',
    headless: false
  })
});

const data = await response.json();
console.log(`Scraped ${data.products_count} products`);
```

## Output Format

Scraped data is saved as CSV with the following columns:
- `name`: Product name
- `price`: Product price (with currency symbol)
- `image_url`: Product image URL

## Important Notes

### Security Warnings

⚠️ **SSL Verification Disabled**: The scraper disables SSL verification globally. This is a security risk and should only be used in controlled environments. Consider removing SSL patches for production use.

### Browser Requirements

- The scraper requires Chrome/Chromium to be installed
- By default, runs in non-headless mode (visible browser window)
- Set `headless: true` in requests to run without UI (may affect Cloudflare bypass)

### Rate Limiting

- Built-in 5-second delay between batch scrapes
- Adjust `scroll_passes` in config to control scraping depth
- Be respectful of target sites' resources

## Troubleshooting

### "No products found"
- Check if the site requires postcode entry
- Verify XPath selectors in `site_config.json`
- Increase `scroll_passes` for sites with lazy loading

### "Cloudflare challenge not bypassed"
- Try running in non-headless mode
- Increase wait times in the scraper
- Some sites may require manual intervention

### "Module not found" errors
- Ensure virtual environment is activated
- Run `pip install -r requirements.txt` again

## Google Image Search Configuration

To use the image search endpoints, configure your Google API credentials in `search_service.py`:

```python
GOOGLE_API_KEY = "your-api-key-here"
CSE_ID = "your-cse-id-here"
```

Get credentials from:
- [Google Cloud Console](https://console.cloud.google.com/)
- [Custom Search Engine](https://programmablesearchengine.google.com/)

## License

This project is for educational purposes. Ensure you comply with the terms of service of any websites you scrape.

## Contributing

To add a new site:
1. Add configuration to `site_config.json`
2. Test XPath selectors
3. Adjust filters as needed
4. Submit a pull request

## Support

For issues or questions:
- Check the interactive API docs at `/docs`
- Review the logs for detailed error messages
- Ensure all dependencies are correctly installed
