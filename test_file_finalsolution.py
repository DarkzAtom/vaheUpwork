import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
import time
import traceback
import math


def get_regular_and_sales_price(soup, url):   # url only for debugging purposes
    """pass here the soup of the page (after choosing the right package amount) and it will locate the regular and the sales price.
    Sales price could be None"""

    # without sales price => regular ----  <span data-product-price-without-tax="" class="price price--withoutTax price--main">$4.89</span>

    # when sales price present => regular ---- <span data-product-non-sale-price-without-tax="" class="price price--non-sale">$13.49</span>

    try:
        check_if_sales_price_is_present = soup.select_one('span.price.price--non-sale').text.strip()

        print(f"DEBUG GRSP:  1. checkifsalepresent: {check_if_sales_price_is_present}")

        regular_price = None
        sales_price = None

        if check_if_sales_price_is_present:
            regular_price = soup.select_one('span.price.price--non-sale').text.strip()
            print(f"DEBUG GRSP:  2. {regular_price}")
            sales_price = soup.select_one('span.price.price--withoutTax.price--main._hasSale').text.strip()
            print(f"DEBUG GRSP:  3. {sales_price}")
        else:
            regular_price = soup.select_one('span.price.price--withoutTax.price--main').text.strip()
            print(f"DEBUG GRSP:  4.  {regular_price}")
            sales_price = None
            print(f"DEBUG GRSP:  5.  {sales_price}")

        if regular_price:
            regular_price = extract_price_amount(regular_price)
        
        if sales_price:
            sales_price = extract_price_amount(sales_price)    

        return regular_price, sales_price
    except Exception as e:
        print(f"error: can't get regular and sales price from {url}, error stacktrace: {e}")
        regular_price, sales_price = None, None
        return regular_price, sales_price


def extract_tier_quantity(text):
    """Get quantity from 'Buy 10' -> 10"""
    match = re.search(r'Buy (\d+)', text)
    return int(match.group(1)) if match else None


def detect_crossed_out_of_stock_size(soup, url):     #url is for debugging purposes
    """Detect if the size is crossed out and of stock"""
    try:
        crossed_out_size = soup.select_one('label.form-label.variant-button.active.unavailable')
        print(f"DEBUG DCOSS:  1. crossed_out_size: {crossed_out_size}")
        if crossed_out_size:
            return True
        else:
            return False
    except Exception as e:
        print(f"error: failed to detect crossed out of stock size in the url {url}, error stacktrace: {e}")
        return False


def extract_discount_info(text):
    # old version where it's allowed for float numbers
    # """Get discount from '(25%)' or '(3.25%)' -> '25%' or '3.25%'"""
    # discount_match = re.search(r'\((\d+\.?\d*)%\)', text)  # Changed this line
    # if discount_match:
    #     return str(float(discount_match.group(1))) + '%'  # Handle decimals properly
    # else:
    #     return None

    """Version 2, where the values are floored to the nearest integer
    Get discount from '(25%)' or '(3.25%)' -> '25%' or '3.25%'"""
    discount_match = re.search(r'\((\d+\.?\d*)%\)', text)  # Changed this line
    if discount_match:
        return str(math.floor(float(discount_match.group(1)))) + '%'  # Handle decimals properly
    else:
        return None


def extract_quantity_from_name(name):
    """Get first number from product name"""
    try:
        match = re.match(r'\d+', str(name))
        return int(match.group()) if match else None
    except TypeError as e:
        print(f'Error extracting quantity: {e}')
        return None


def extract_price_amount(text):
    """Get '21.49' from '$21.49' or '$21.49 - $298.99' (takes first price)"""
    if not text:
        return None
    
    first_price = text.split('-')[0].strip()
    
    # extract number from first price
    match = re.search(r'\$(\d+\.?\d*)', first_price)
    return match.group(1) if match else None


def scrape_no_tiers(soup, url):
    """Handle products with no tier pricing"""

    regular_price, sales_price = get_regular_and_sales_price(soup, url)   # passing url only in debugging purposes

    return {
        "regular_price": regular_price,
        "sales_price": sales_price,
        "tier_string": "No tiers present"
    }


def build_tier_list(soup):
    """Extract all tier data and return list of {quantity, discount}"""
    tiers = soup.select('div.tier-button')
    print(f"🔍 DEBUG: Found {len(tiers)} tier buttons")
    
    tier_list = []
    
    for i, tier in enumerate(tiers):
        print(f"🔍 DEBUG: Processing tier {i+1}")
        
        quantity_elem = tier.select_one("div.quantity-range")
        discount_elem = tier.select_one("div.discount-info")
        
        print(f"🔍 DEBUG: quantity_elem found: {quantity_elem is not None}")
        print(f"🔍 DEBUG: discount_elem found: {discount_elem is not None}")
        
        if quantity_elem:
            print(f"🔍 DEBUG: quantity_elem text: '{quantity_elem.text.strip()}'")
        if discount_elem:
            print(f"🔍 DEBUG: discount_elem text: '{discount_elem.text.strip()}'")

        if not (quantity_elem and discount_elem):
            print(f"❌ DEBUG: Skipping tier {i+1} - missing elements")
            continue

        quantity = extract_tier_quantity(quantity_elem.text)
        discount = extract_discount_info(discount_elem.text)
        
        print(f"🔍 DEBUG: extracted quantity: {quantity}")
        print(f"🔍 DEBUG: extracted discount: {discount}")

        if quantity and discount:
            tier_list.append({'quantity': quantity, 'discount': discount})
            print(f"✅ DEBUG: Added tier: {quantity}:{discount}")
        else:
            print(f"❌ DEBUG: Skipping tier {i+1} - invalid quantity/discount")

    print(f"🔍 DEBUG: Final tier_list: {tier_list}")
    return tier_list


def scrape_tier_data(url, quantity_from_excel=None):
    """Main scraping function - same logic as original"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Check if tiers exist
        tiers_div = soup.select_one('div.tier-buttons')
        if not tiers_div:
            return scrape_no_tiers(soup, url)

        # Get tier data
        tier_list = build_tier_list(soup)

        print(f"DEBUG GRSP:  6. tier_list = {tier_list}")

        # Build tier string
        tier_string = None
        if tier_list:
            tier_string = ",".join([f"{t['quantity']}:{t['discount'].replace('%', '')}" for t in tier_list])

        # Get price for specific quantity if needed
        regular_price, sales_price = get_regular_and_sales_price(soup, url)  # passing url only for debugging purposes

        return {
            'regular_price': regular_price,
            'sales_price': sales_price,
            'tier_string': tier_string
        }

    except requests.RequestException as e:
        return {
            'regular_price': None,
            'sales_price': None, 
            'tier_string': f"Request error: {str(e)}"
        }
    except Exception as e:
        return {
            'regular_price': None,
            'sales_price': None,
            'tier_string': f"Parsing error: {str(e)}"
        }


def process_excel_file(input_file, output_file=None):
    """Process Excel file and scrape data for each URL"""
    if output_file is None:
        output_file = input_file.replace('.xlsx', '_processed.xlsx')

    # Load Excel file
    try:
        df = pd.read_excel(input_file)
    except Exception as e:
        print(f'Error reading Excel file: {e}')
        return

    print(f"Processing {len(df)} URLs...")

    # Process each row
    for index, row in df.iterrows():
        url = row.iloc[0]

        # Get quantity from Name column
        quantity = extract_quantity_from_name(row.get('Name', ''))
        print(f'Quantity: {quantity}, Row: {int(index) + 1}')

        # Skip empty URLs
        if pd.isna(url) or url == '':
            df.loc[index, 'PLK Regular price'] = 'No URL provided'
            df.loc[index, 'PLK Percentage Tiered Prices'] = 'No URL provided'
            continue

        # Only process pureleafkratom URLs
        if "pureleafkratom" not in url:
            continue

        print(f"Processing row {int(index) + 1}: {url}")

        # Scrape the data
        scraped_data = scrape_tier_data(url, quantity)

        print(f'ANCHOR DEBUG: scraped_data = {scraped_data}')

        # Update Excel columns
        try:
            if scraped_data.get('sales_price') and scraped_data.get('regular_price'):
                clean_sales_price = scraped_data['sales_price'].replace('$', '')
                clean_regular_price = scraped_data['regular_price'].replace('$', '')
                df.loc[index, "PLK Regular price"] = clean_sales_price
                df.loc[index, "PLK Sale price"] = clean_regular_price

            elif scraped_data.get('regular_price'):
                clean_regular_price = scraped_data['regular_price'].replace('$', '')
                df.loc[index, "PLK Regular price"] = clean_regular_price

            df.loc[index, "PLK Percentage Tiered Prices"] = scraped_data.get('tier_string')

            print(f"Regular Price: {scraped_data.get('regular_price')}")
            print(f"Tier string: {scraped_data.get('tier_string')}")

        except Exception as e:
            print(f'Error updating row for {url}: {e}')
            traceback.print_exc()
            continue

        # Be nice to the server
        time.sleep(3)

    # Save results
    df.to_excel(output_file, index=False)
    print(f"\nResults saved to: {output_file}")


def test_single_url():
    """Test with one URL"""
    url = "https://pureleafkratom.com/products/7ohmz-kratom-7-hydroxymitragynine-extract-tablets-14mg.html"
    print(f"Testing URL: {url}")

    result = scrape_tier_data(url)
    print(f"Regular Price: {result.get('regular_price')}")
    print(f"Tier String: {result.get('tier_string')}")


# if __name__ == '__main__':
#     # Uncomment to test single URL
#     # test_single_url()

#     # Uncomment to run full program
#     input_file = "input_copy.xlsx"
#     process_excel_file(input_file)


# link with tier


# TEST IF NAME MAIN to test out single functions (comment out the one above and uncomment the one below)
if __name__ == '__main__':
    url = 'https://pureleafkratom.com/products/lucky-7-7-oh-chewable-tablets-natural-18mg-per-tablet.html'
    response = requests.get(url, timeout=10)
    soup = BeautifulSoup(response.text, 'html.parser')
    print(f"DEBUG DCOSS:  2. soup: {soup.prettify()}")
    out_of_stock = detect_crossed_out_of_stock_size(soup, url)
    print(f"out_of_stock: {out_of_stock}")