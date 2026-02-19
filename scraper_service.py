"""
E-commerce Scraper with SeleniumBase Undetected Chrome
Bypasses Cloudflare using SeleniumBase's uc mode (no cookies needed)
"""

from seleniumbase import Driver
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import requests
import urllib3
import os
import ssl
import time
import json
import csv
import re
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import logging

logger = logging.getLogger(__name__)

# Disable SSL verification globally - MUST be before any imports
os.environ['REQUESTS_CA_BUNDLE'] = ''
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['SSL_CERT_FILE'] = ''
os.environ['REQUESTS_VERIFY'] = 'False'
os.environ['PYTHONHTTPSVERIFY'] = '0'

# Monkey-patch SSL context
_original_create_default_context = ssl.create_default_context


def _create_unverified_context(*args, **kwargs):
    context = _original_create_default_context(*args, **kwargs)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


ssl.create_default_context = _create_unverified_context
ssl._create_default_https_context = ssl._create_unverified_context

# Patch requests library to disable SSL verification
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# Monkey-patch requests Session to always use verify=False
_original_request = requests.Session.request


def _patched_request(self, *args, **kwargs):
    kwargs['verify'] = False
    return _original_request(self, *args, **kwargs)


requests.Session.request = _patched_request

# Patch requests.get, requests.post, etc.
_original_get = requests.get
_original_post = requests.post


def _patched_get(*args, **kwargs):
    kwargs['verify'] = False
    return _original_get(*args, **kwargs)


def _patched_post(*args, **kwargs):
    kwargs['verify'] = False
    return _original_post(*args, **kwargs)


requests.get = _patched_get
requests.post = _patched_post


class UndetectedScraper:
    """Scraper using SeleniumBase undetected Chrome mode"""

    def __init__(self, config_file='site_config.json'):
        try:
            with open(config_file, 'r') as f:
                self.configs = json.load(f)
        except FileNotFoundError:
            logger.info(f"⚠️  Config file '{config_file}' not found, using automatic extraction mode")
            self.configs = {}
        self.driver = None

    def detect_site(self, url):
        """Detect site type from URL"""
        domain = urlparse(url).netloc.lower()
        if 'deliveroo' in domain:
            return 'deliveroo'
        elif 'just-eat' in domain or 'justeat' in domain:
            return 'justeat'
        elif 'snappyshopper' in domain or 'snappy' in domain:
            return 'snappyshopper'
        return 'generic'

    def handle_postcode(self, config):
        """Enter postcode if required by site"""
        try:
            postcode = config.get('postcode', 'GL52 3DT')
            logger.info(f"📍 Entering postcode: {postcode}...")

            time.sleep(3)  # Wait for page to fully load

            # Step 1: Try Selenium native methods first
            logger.info("   Attempting to find and fill input...")

            input_filled = False

            # Method 1: Try Selenium's find_element with various selectors
            selectors = [
                (By.XPATH, '//input[contains(translate(@placeholder, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "postcode")]'),
                (By.XPATH, '//input[contains(translate(@placeholder, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "address")]'),
                (By.CSS_SELECTOR, 'input[id*="location"]'),
                (By.CSS_SELECTOR, 'input[id*="search"]'),
                (By.CSS_SELECTOR, 'input[type="text"]'),
            ]

            for by, selector in selectors:
                try:
                    logger.info(f"   Trying selector: {selector}")
                    elements = self.driver.find_elements(by, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            logger.info(f"   → Found visible input!")
                            elem.click()
                            time.sleep(0.5)
                            elem.clear()
                            elem.send_keys(postcode)
                            logger.info(f"   ✅ Filled with: {postcode}")
                            input_filled = True
                            break
                    if input_filled:
                        break
                except Exception as e:
                    logger.debug(f"   ❌ Failed: {str(e)[:50]}")
                    continue

            # Method 2: If above failed, try JavaScript
            if not input_filled:
                logger.info("   Trying JavaScript method...")
                script = f"""
                var inputs = Array.from(document.querySelectorAll('input'));
                console.log('Total inputs found:', inputs.length);
                
                for (var input of inputs) {{
                    var rect = input.getBoundingClientRect();
                    var style = window.getComputedStyle(input);
                    var isVisible = rect.width > 0 && rect.height > 0 && 
                                    style.display !== 'none' && 
                                    style.visibility !== 'hidden';
                    
                    if (isVisible) {{
                        console.log('Visible input:', {{
                            id: input.id,
                            name: input.name,
                            placeholder: input.placeholder,
                            type: input.type
                        }});
                        
                        input.focus();
                        input.click();
                        input.value = '{postcode}';
                        
                        // Trigger all possible events
                        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        input.dispatchEvent(new Event('keyup', {{ bubbles: true }}));
                        
                        return {{ 
                            success: true, 
                            id: input.id, 
                            placeholder: input.placeholder,
                            value: input.value
                        }};
                    }}
                }}
                return {{ success: false }};
                """

                result = self.driver.execute_script(script)
                logger.info(f"   JavaScript result: {result}")
                input_filled = result.get('success', False)

            if not input_filled:
                logger.warning("   ⚠️  Could not enter postcode - skipping")
                return

            logger.info(f"   ✅ Postcode entered successfully!")
            time.sleep(2)

            # Step 2: Click search button
            logger.info("   Looking for search/submit button...")

            button_selectors = [
                (By.CSS_SELECTOR, 'button[type="submit"]'),
                (By.XPATH, '//button[contains(translate(@aria-label, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "find")]'),
                (By.XPATH, '//button[contains(translate(@aria-label, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "search")]'),
                (By.XPATH, '//button[contains(text(), "Find")]'),
                (By.XPATH, '//button[contains(text(), "Search")]'),
                (By.XPATH, '//button[contains(text(), "Go")]'),
            ]

            button_clicked = False

            # First check for site-specific popup button
            popup_search_button = config.get('postcode_selectors', {}).get('popup_search_button')
            if popup_search_button:
                try:
                    logger.info(f"   Trying site-specific popup button: {popup_search_button}")
                    popup_btn = self.driver.find_element(By.XPATH, popup_search_button)
                    if popup_btn and popup_btn.is_displayed():
                        popup_btn.click()
                        logger.info(f"   ✅ Clicked popup search button")
                        button_clicked = True
                        time.sleep(5)
                except Exception as e:
                    logger.debug(f"   Popup button not found: {e}")

            # Try standard button selectors if popup button not found
            if not button_clicked:
                for by, selector in button_selectors:
                    try:
                        logger.info(f"   Trying button: {selector}")
                        buttons = self.driver.find_elements(by, selector)
                        if buttons:
                            logger.info(f"     → Found {len(buttons)} button(s)")
                            for idx, btn in enumerate(buttons):
                                try:
                                    if btn.is_displayed():
                                        logger.info(f"     → Button {idx+1} is visible, clicking...")
                                        btn.click()
                                        logger.info(f"   ✅ Clicked button with selector: {selector}")
                                        button_clicked = True
                                        time.sleep(5)
                                        break
                                except:
                                    continue
                            if button_clicked:
                                break
                    except Exception as e:
                        logger.debug(f"     ❌ {str(e)[:50]}")

            if not button_clicked:
                # Fallback: Press Enter
                logger.info("   No button clicked, pressing Enter as fallback...")
                try:
                    inputs = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="text"]')
                    for inp in inputs:
                        if inp.is_displayed():
                            inp.send_keys(Keys.RETURN)
                            logger.info("   ✅ Pressed Enter")
                            time.sleep(5)
                            break
                except Exception as e:
                    logger.error(f"   ❌ Enter failed: {e}")

            # Step 3: Handle popups
            logger.info("   Checking for popups/modals...")
            time.sleep(2)

            popup_close_selectors = [
                (By.XPATH, '//button[contains(translate(@aria-label, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "close")]'),
                (By.XPATH, '//button[contains(translate(@aria-label, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "dismiss")]'),
                (By.CSS_SELECTOR, 'button.close'),
                (By.CSS_SELECTOR, 'button[class*="close"]'),
                (By.XPATH, '//button[contains(text(), "Close")]'),
                (By.XPATH, '//button[contains(text(), "×")]'),
                (By.XPATH, '//button[contains(text(), "X")]'),
            ]

            popup_closed = False
            for by, selector in popup_close_selectors:
                try:
                    close_buttons = self.driver.find_elements(by, selector)
                    if close_buttons:
                        for btn in close_buttons:
                            try:
                                if btn.is_displayed():
                                    btn.click()
                                    logger.info(f"   ✅ Closed popup with: {selector}")
                                    popup_closed = True
                                    time.sleep(2)
                                    break
                            except:
                                continue
                        if popup_closed:
                            break
                except:
                    pass

            if popup_closed:
                logger.info("   ✅ Popup closed successfully")
            else:
                logger.info("   ℹ️  No popup detected or already closed")

        except Exception as e:
            logger.error(f"   ⚠️  Postcode handling failed: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)

    def normalize_image_url(self, url):
        """Trim image URL to end at .jpg or .jpeg"""
        if not url or url == 'N/A':
            return url

        if '.jpg' in url.lower():
            pos = url.lower().find('.jpg')
            if pos != -1:
                return url[:pos + 4]

        if '.jpeg' in url.lower():
            pos = url.lower().find('.jpeg')
            if pos != -1:
                return url[:pos + 5]

        return url

    def _is_actual_price(self, price_elem):
        """
        Validate if a price element represents an actual product price.
        Filters out: strikethrough prices, discount amounts, promotional text, bundle prices, price ranges.
        """
        try:
            price_text = price_elem.text.strip()
            
            if not price_text:
                return False
            
            # Skip price ranges
            if re.search(r'£\d+\.?\d*\s*-\s*£\d+\.?\d*', price_text):
                return False
            
            # Skip strikethrough prices
            try:
                text_decoration = price_elem.value_of_css_property('text-decoration')
                if 'line-through' in text_decoration:
                    return False
            except:
                pass
            
            # Skip promotional keywords
            price_lower = price_text.lower()
            
            if re.search(r'\d+\s+for\s+[£$€]', price_lower):
                return False
            
            if ' off' in price_lower or 'save £' in price_lower or 'save $' in price_lower:
                return False
            
            if price_lower.startswith(('was ', 'from ', 'save ')):
                return False
            
            # Skip very small font sizes
            try:
                font_size = price_elem.value_of_css_property('font-size')
                if font_size and float(font_size.replace('px', '')) < 12:
                    return False
            except:
                pass
            
            # Check parent context
            try:
                parent = price_elem.find_element(By.XPATH, '..')
                parent_text = parent.text.lower() if parent.text else ''
                
                if len(parent_text) < 20:
                    return True
                
                price_position = parent_text.find(price_text.lower())
                if price_position >= 0:
                    context_start = max(0, price_position - 30)
                    context_end = min(len(parent_text), price_position + len(price_text) + 30)
                    price_context = parent_text[context_start:context_end]
                    
                    close_keywords = ['off', 'save', 'was £', 'was $', 'for £', 'for $']
                    for keyword in close_keywords:
                        if keyword in price_context:
                            if keyword == 'was £' or keyword == 'was $':
                                if re.search(r'was [£$]\d+.*?' + re.escape(price_text), price_context):
                                    continue
                            return False
            except:
                pass
            
            return True
            
        except Exception as e:
            return True

    def _extract_items_from_viewport(self, extracted_items, site_type):
        """Extract product items currently visible in viewport"""
        new_products = []
        config = self.configs.get(site_type, {})
        extraction_config = config.get('extraction', {})

        try:
            price_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), '£')]")
            logger.info(f"      → Found {len(price_elements)} elements with £ symbol")

            viewport_count = 0
            extracted_count = 0
            filtered_by_price_check = 0
            filtered_by_duplicate = 0
            failed_extraction = 0

            for price_elem in price_elements:
                try:
                    is_in_viewport = self.driver.execute_script(
                        "var elem = arguments[0];"
                        "var rect = elem.getBoundingClientRect();"
                        "return (rect.bottom >= 0 && rect.top <= window.innerHeight);",
                        price_elem
                    )

                    if not is_in_viewport:
                        continue

                    viewport_count += 1

                    if not self._is_actual_price(price_elem):
                        filtered_by_price_check += 1
                        continue

                    product_data = self._extract_product_data_from_price(
                        price_elem, extraction_config, debug=(extracted_count < 10))

                    if product_data:
                        # Improved duplicate detection: include image_url for better uniqueness
                        item_hash = f"{product_data['name']}_{product_data['price']}_{product_data['image_url']}"
                        if item_hash not in extracted_items:
                            extracted_items.add(item_hash)
                            new_products.append(product_data)
                            extracted_count += 1
                        else:
                            filtered_by_duplicate += 1
                    else:
                        failed_extraction += 1

                except Exception as ex:
                    continue

        except Exception as e:
            logger.error(f"      ❌ Error in viewport extraction: {e}")

        logger.info(f"      → In viewport: {viewport_count}, Extracted: {extracted_count}")
        logger.info(f"      → Filtered: {filtered_by_price_check} (price check), {filtered_by_duplicate} (duplicate), {failed_extraction} (extraction failed)")
        return new_products

    def _normalize_url(self, url, base_url=''):
        """Normalize URL with base URL if needed"""
        if not url:
            return 'N/A'

        if url.startswith('http'):
            return url
        elif url.startswith('//'):
            return 'https:' + url
        elif url.startswith('/'):
            return base_url + url if base_url else url
        else:
            return base_url + '/' + url if base_url else url

    def _apply_text_filters(self, text, filters):
        """Apply filters to text based on config"""
        if not text:
            return False

        for filter_name in filters:
            if filter_name == 'no_price':
                if '£' in text or '$' in text:
                    return False

            elif filter_name == 'no_calories':
                if 'cal' in text.lower() or 'kcal' in text.lower():
                    return False

            elif filter_name == 'no_from_prefix':
                if text.startswith('From'):
                    return False

            elif filter_name == 'no_your_current_prefix':
                if text.startswith('Your Current'):
                    return False

            elif filter_name == 'no_digit_only':
                if text.replace('.', '').replace(',', '').isdigit():
                    return False

            elif filter_name.startswith('min_length:'):
                min_len = int(filter_name.split(':')[1])
                if len(text) < min_len:
                    return False

            elif filter_name == 'no_common_words':
                if text.lower() in ['from', 'your current order', 'order', 'current', 'popular', 'view all', 'add']:
                    return False

        return True

    def _auto_extract_name(self, price_elem, debug=False):
        """Automatically extract product name using smart pattern detection"""
        try:
            # Strategy 1: Look for heading tags (h1-h6) in ancestors
            for ancestor_level in range(1, 6):
                try:
                    headings = price_elem.find_elements(By.XPATH, f"ancestor::*[{ancestor_level}]//h1 | ancestor::*[{ancestor_level}]//h2 | ancestor::*[{ancestor_level}]//h3 | ancestor::*[{ancestor_level}]//h4")
                    for heading in headings:
                        text = heading.text.strip()
                        if text and len(text) >= 3 and '£' not in text and '$' not in text:
                            if debug:
                                logger.info(f"         ✅ Auto-found name (heading): {text}")
                            return text
                except:
                    pass
            
            # Strategy 2: Look for common product name class patterns
            class_patterns = [
                "product-name", "product-title", "item-name", "item-title",
                "product_name", "product_title", "item_name", "item_title",
                "name", "title"
            ]
            for ancestor_level in range(1, 6):
                for pattern in class_patterns:
                    try:
                        elements = price_elem.find_elements(By.XPATH, f"ancestor::*[{ancestor_level}]//*[contains(@class, '{pattern}')]")
                        for elem in elements:
                            text = elem.text.strip()
                            if text and len(text) >= 3 and '£' not in text and '$' not in text:
                                if debug:
                                    logger.info(f"         ✅ Auto-found name (class pattern): {text}")
                                return text
                    except:
                        pass
            
            # Strategy 3: Look for <p> or <span> tags with substantial text
            for ancestor_level in range(1, 5):
                try:
                    text_elements = price_elem.find_elements(By.XPATH, f"ancestor::*[{ancestor_level}]//p | ancestor::*[{ancestor_level}]//span")
                    for elem in text_elements:
                        text = elem.text.strip()
                        # Filter out prices, calories, and short text
                        if (text and len(text) >= 10 and 
                            '£' not in text and '$' not in text and 
                            'cal' not in text.lower() and 'kcal' not in text.lower()):
                            if debug:
                                logger.info(f"         ✅ Auto-found name (text element): {text}")
                            return text.split('\n')[0]  # Take first line
                except:
                    pass
            
            if debug:
                logger.info(f"         ❌ Auto-extraction: No name found")
            return None
            
        except Exception as e:
            if debug:
                logger.error(f"         ⚠️  Auto-extraction error: {e}")
            return None

    def _auto_extract_image(self, price_elem, debug=False):
        """Automatically extract product image using smart pattern detection"""
        try:
            # Strategy 1: Look for <img> tags in ancestors
            for ancestor_level in range(1, 6):
                try:
                    images = price_elem.find_elements(By.XPATH, f"ancestor::*[{ancestor_level}]//img")
                    for img in images:
                        # Try src first
                        src = img.get_attribute('src')
                        if src and src.startswith('http'):
                            if debug:
                                logger.info(f"         ✅ Auto-found image (src): {src[:50]}...")
                            return self.normalize_image_url(src)
                        
                        # Try srcset
                        srcset = img.get_attribute('srcset')
                        if srcset:
                            urls = [s.strip().split()[0] for s in srcset.split(',') if s.strip()]
                            if urls:
                                url = urls[-1]  # Get highest resolution
                                if debug:
                                    logger.info(f"         ✅ Auto-found image (srcset): {url[:50]}...")
                                return self.normalize_image_url(url)
                except:
                    pass
            
            # Strategy 2: Look for div with role="img" and background image in style
            for ancestor_level in range(1, 6):
                try:
                    divs = price_elem.find_elements(By.XPATH, f"ancestor::*[{ancestor_level}]//div[@role='img']")
                    for div in divs:
                        style = div.get_attribute('style')
                        if style and 'url(' in style:
                            url_match = re.search(r'url\(["\']?([^"\'()]+)["\']?\)', style)
                            if url_match:
                                url = url_match.group(1)
                                if debug:
                                    logger.info(f"         ✅ Auto-found image (background): {url[:50]}...")
                                return self.normalize_image_url(url)
                except:
                    pass
            
            # Strategy 3: Look for any element with background-image in style
            for ancestor_level in range(1, 5):
                try:
                    elements = price_elem.find_elements(By.XPATH, f"ancestor::*[{ancestor_level}]//*[@style]")
                    for elem in elements:
                        style = elem.get_attribute('style')
                        if style and 'background-image' in style and 'url(' in style:
                            url_match = re.search(r'url\(["\']?([^"\'()]+)["\']?\)', style)
                            if url_match:
                                url = url_match.group(1)
                                if debug:
                                    logger.info(f"         ✅ Auto-found image (background-image): {url[:50]}...")
                                return self.normalize_image_url(url)
                except:
                    pass
            
            if debug:
                logger.info(f"         ❌ Auto-extraction: No image found")
            return 'N/A'
            
        except Exception as e:
            if debug:
                logger.error(f"         ⚠️  Auto-extraction error: {e}")
            return 'N/A'

    def _extract_product_data_from_price(self, price_elem, extraction_config, debug=False):
        """Extract name, price, and image by searching up/down from price element"""
        try:
            # Extract PRICE
            price = None
            price_text = price_elem.text.strip()

            if re.search(r'[£$]\d+\.?\d*\s*-\s*[£$]\d+\.?\d*', price_text):
                return None

            if '£' in price_text or '$' in price_text:
                price_matches = re.findall(r'[£$]\d+\.?\d*', price_text)
                if price_matches:
                    price = price_matches[0]
                    if debug:
                        logger.info(f"\n      🔍 DEBUG Item:")
                        logger.info(f"         💰 Price: {price}")

            if not price:
                return None

            # Extract NAME
            name = None
            name_config = extraction_config.get('name', {})
            name_xpath = name_config.get('xpath', '')
            filters = name_config.get('filters', [])

            if debug:
                logger.info(f"         📝 Searching for name with XPath: {name_xpath}")

            # Try config-based extraction first
            if name_xpath:
                try:
                    try:
                        name_elem = price_elem.find_element(By.XPATH, name_xpath)
                        name_elements = [name_elem] if name_elem else []
                    except:
                        name_elements = price_elem.find_elements(By.XPATH, name_xpath)

                    if debug:
                        logger.info(f"            → Found {len(name_elements)} name elements")

                    for elem in name_elements:
                        text = elem.text.strip()
                        if '\n' in text:
                            text = text.split('\n')[0].strip()

                        if debug:
                            logger.info(f"            → Candidate text: '{text}'")

                        if self._apply_text_filters(text, filters):
                            name = text
                            if debug:
                                logger.info(f"         ✅ Name: {name}")
                            break
                        elif debug:
                            logger.info(f"            ✖️  Filtered out by rules")
                except Exception as e:
                    if debug:
                        logger.error(f"            ⚠️  Error searching for name: {e}")

            # Fall back to automatic extraction if config-based failed
            if not name:
                if debug:
                    logger.info(f"         🤖 Trying automatic name extraction...")
                name = self._auto_extract_name(price_elem, debug=debug)

            if not name:
                if debug:
                    logger.info(f"         ❌ No name found")
                return None

            # Extract IMAGE
            image_url = 'N/A'
            image_config = extraction_config.get('image', {})
            image_xpath = image_config.get('xpath', '')
            attribute = image_config.get('attribute', 'src')

            if debug:
                logger.info(f"         🖼️  Searching for image with XPath: {image_xpath}")

            # Try config-based extraction first
            if image_xpath:
                try:
                    try:
                        img_elem = price_elem.find_element(By.XPATH, image_xpath)
                        img_elements = [img_elem] if img_elem else []
                    except:
                        img_elements = price_elem.find_elements(By.XPATH, image_xpath)

                    if debug:
                        logger.info(f"            → Found {len(img_elements)} image elements")

                    for elem in img_elements:
                        attr_value = elem.get_attribute(attribute)

                        if not attr_value:
                            fallback_attr = image_config.get('fallback_attribute')
                            if fallback_attr:
                                attr_value = elem.get_attribute(fallback_attr)

                        if attr_value:
                            if attribute == 'srcset':
                                urls = [s.strip().split()[0] for s in attr_value.split(',') if s.strip()]
                                if urls:
                                    srcset_index = image_config.get('srcset_index', -1)
                                    image_url = urls[srcset_index]
                                    image_url = self._normalize_url(image_url, image_config.get('base_url', ''))
                                    break

                            elif attribute == 'style':
                                pattern = image_config.get('pattern', r'url\(["\']?([^"\'()]+)["\']?\)')
                                url_match = re.search(pattern, attr_value)
                                if url_match:
                                    image_url = url_match.group(1)
                                    break

                            else:
                                image_url = self._normalize_url(attr_value, image_config.get('base_url', ''))
                                if image_url != 'N/A':
                                    break

                    # Apply trim_after logic
                    if image_url != 'N/A':
                        trim_after = image_config.get('trim_after', [])
                        if isinstance(trim_after, str):
                            trim_after = [trim_after] if trim_after else []

                        for trim_ext in trim_after:
                            if trim_ext and trim_ext in image_url.lower():
                                pos = image_url.lower().find(trim_ext)
                                image_url = image_url[:pos + len(trim_ext)]
                                break

                    # For Just Eat, always append .jpg if not already present
                    if image_url != 'N/A' and 'just-eat' in image_url.lower():
                        if not image_url.lower().endswith(('.jpg', '.jpeg')):
                            image_url += '.jpg'

                except Exception as e:
                    if debug:
                        logger.error(f"            ⚠️  Error searching for image: {e}")

            # Fall back to automatic extraction if config-based failed
            if image_url == 'N/A':
                if debug:
                    logger.info(f"         🤖 Trying automatic image extraction...")
                image_url = self._auto_extract_image(price_elem, debug=debug)

            if debug:
                if image_url != 'N/A':
                    logger.info(f"         ✅ Image: {image_url[:50]}...")
                else:
                    logger.info(f"         ❌ No image found")

            return {
                'name': name,
                'price': price,
                'image_url': image_url
            }

        except Exception as ex:
            if debug:
                logger.error(f"         ❌ Error extracting product data: {ex}")
            return None

    def scrape_site(self, url, headless=False):
        """Scrape using SeleniumBase undetected mode"""
        site_type = self.detect_site(url)
        config = self.configs.get(site_type, {})

        logger.info(f"\n{'='*60}")
        logger.info(f"🎯 Target: {config.get('name', 'Unknown Site')}")
        logger.info(f"🔓 Method: SeleniumBase Undetected Chrome")
        logger.info(f"{'='*60}\n")

        products = []

        try:
            # Setup undetected Chrome driver
            logger.info("🚀 Launching undetected Chrome browser...")
            
            if headless:
                # For truly hidden mode, use additional Chrome options
                from selenium.webdriver.chrome.options import Options
                chrome_options = Options()
                chrome_options.add_argument("--headless=new")  # New headless mode
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--window-position=-2400,-2400")  # Move window off-screen
                chrome_options.add_argument("--window-size=1920,1080")
                chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
                chrome_options.add_experimental_option('useAutomationExtension', False)
                
                logger.info("   Running in HIDDEN mode (headless + off-screen)")
                self.driver = Driver(uc=True, headless2=True, chromium_arg="--headless=new")
            else:
                logger.info("   Running in VISIBLE mode")
                self.driver = Driver(uc=True, headless=False)

            # Navigate with special reconnect method
            logger.info(f"🌐 Loading: {url}")
            self.driver.uc_open_with_reconnect(url, reconnect_time=4)

            # Wait for page to load
            logger.info("⏳ Waiting for page to load...")
            time.sleep(3)

            # Wait for document ready state
            try:
                for _ in range(10):
                    ready_state = self.driver.execute_script("return document.readyState")
                    if ready_state == "complete":
                        break
                    time.sleep(1)
                logger.info("✅ Page ready state: complete")
            except:
                pass

            # Handle Cloudflare captcha if present
            logger.info("🔍 Checking for Cloudflare challenge...")
            try:
                self.driver.uc_gui_click_captcha()
                logger.info("✅ Cloudflare challenge handled!")
                time.sleep(5)
            except:
                logger.info("ℹ️  No Cloudflare challenge detected")

            time.sleep(5)

            # Check if we got through
            page_content = self.driver.page_source.lower()
            if 'cloudflare' in page_content and 'challenge' in page_content:
                logger.warning("⚠️  Still showing Cloudflare challenge page")
                time.sleep(10)
            else:
                logger.info("✅ Successfully bypassed Cloudflare!")

            # Handle postcode if required
            if config.get('requires_postcode', False) or (site_type == 'deliveroo' and '/menu/' not in url):
                logger.info("\n📍 Attempting to enter postcode...")
                self.handle_postcode(config)
                time.sleep(5)

                logger.info("⏳ Waiting for page to reload after postcode entry...")
                time.sleep(10)

                logger.info("⏳ Waiting for products to load...")
                try:
                    for attempt in range(15):
                        price_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), '£')]")
                        if len(price_elements) > 5:
                            logger.info(f"✅ Found {len(price_elements)} price elements, page loaded")
                            break
                        if attempt % 3 == 0:
                            logger.info(f"   ... waiting for products (attempt {attempt+1}/15, found {len(price_elements)} prices)")
                        time.sleep(1)
                    else:
                        logger.warning(f"⚠️  Warning: Only found {len(price_elements)} price elements after 15s wait")
                except Exception as e:
                    logger.error(f"⚠️  Error waiting for products: {e}")

            # INCREMENTAL SCROLL AND EXTRACT
            logger.info("\n📜 Scrolling incrementally and extracting data...")

            products = []
            extracted_items = set()

            scroll_passes = config.get('scroll_passes', 20)
            current_scroll_position = 0
            scroll_step = 800

            last_height = self.driver.execute_script("return document.body.scrollHeight")
            no_change_count = 0
            max_no_change = 3

            logger.info(f"   Starting incremental scroll and extract (will scroll by {scroll_step}px each time)")

            for i in range(scroll_passes):
                logger.info(f"\n   📍 Scroll pass {i+1}/{scroll_passes}")

                current_scroll_position += scroll_step
                self.driver.execute_script(f"window.scrollTo(0, {current_scroll_position})")

                if i < 10:
                    time.sleep(4)
                else:
                    time.sleep(2.5)

                time.sleep(0.5)
                try:
                    self.driver.execute_script("return document.readyState")
                except:
                    pass
                time.sleep(1)

                logger.info(f"   🔍 Extracting items from current view...")
                viewport_items = self._extract_items_from_viewport(extracted_items, site_type)

                if viewport_items:
                    products.extend(viewport_items)
                    logger.info(f"   ✅ Extracted {len(viewport_items)} new items (Total so far: {len(products)})")
                else:
                    logger.info(f"   → No new items found in this section")

                new_height = self.driver.execute_script("return document.body.scrollHeight")
                current_position = self.driver.execute_script("return window.pageYOffset + window.innerHeight")

                if current_position >= new_height - 100:
                    if new_height == last_height:
                        no_change_count += 1
                        logger.info(f"   → At bottom, no new content (count: {no_change_count}/{max_no_change})")

                        if no_change_count >= max_no_change:
                            logger.info(f"   ✅ Reached end of page after {no_change_count} checks")
                            break
                    else:
                        logger.info(f"   → New content loaded at bottom (height: {last_height} → {new_height})")
                        last_height = new_height
                        no_change_count = 0
                else:
                    no_change_count = 0

            # Final passes - FULL PAGE EXTRACTION (not just viewport)
            logger.info(f"\n   📍 Final pass: scrolling to absolute bottom...")
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)

            logger.info(f"   🔍 Extracting any remaining items from viewport...")
            final_items = self._extract_items_from_viewport(extracted_items, site_type)
            if final_items:
                products.extend(final_items)
                logger.info(f"   ✅ Extracted {len(final_items)} final items from viewport")

            # NEW: Full-page extraction pass to catch any missed products
            logger.info(f"\n   🌐 FULL PAGE EXTRACTION: Processing all products on page...")
            logger.info(f"   (This will catch any products missed by viewport detection)")
            
            try:
                # Get extraction config for this site type
                extraction_config = config.get('extraction', {})
                
                all_price_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), '£')]")
                logger.info(f"   → Found {len(all_price_elements)} total price elements on page")
                
                full_page_count = 0
                for idx, price_elem in enumerate(all_price_elements):
                    try:
                        if not self._is_actual_price(price_elem):
                            continue
                        
                        product_data = self._extract_product_data_from_price(
                            price_elem, extraction_config, debug=False)
                        
                        if product_data:
                            item_hash = f"{product_data['name']}_{product_data['price']}_{product_data['image_url']}"
                            if item_hash not in extracted_items:
                                extracted_items.add(item_hash)
                                products.append(product_data)
                                full_page_count += 1
                                logger.info(f"   → Found missed product #{full_page_count}: {product_data['name']} - {product_data['price']}")
                    except Exception as ex:
                        continue
                
                if full_page_count > 0:
                    logger.info(f"   ✅ Full-page extraction found {full_page_count} additional products!")
                else:
                    logger.info(f"   ✅ Full-page extraction complete - no additional products found")
                    
            except Exception as e:
                logger.error(f"   ⚠️ Error in full-page extraction: {e}")

            logger.info(f"\n🎯 Total products extracted: {len(products)}")
            logger.info(f"✅ Extracted {len(products)} products from {config.get('name', 'Unknown Site')}")

        except Exception as e:
            logger.error(f"\n❌ Error scraping {config.get('name', 'Unknown Site')}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.driver:
                self.driver.quit()

        return products

    def save_to_csv(self, products, site_name=None, filename=None):
        """Save products to CSV file"""
        if not products:
            logger.info("No products to save")
            return None

        if not filename:
            if site_name:
                clean_name = site_name.lower().replace(' ', '_')
                filename = f'{clean_name}_products.csv'
            else:
                filename = 'ecommerce_products.csv'

        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['name', 'price', 'image_url'])
            writer.writeheader()
            writer.writerows(products)

        logger.info(f"\n💾 Saved {len(products)} products to {filename}")
        return filename
