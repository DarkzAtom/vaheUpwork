import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
import time
import traceback


def get_regular_and_sales_price(soup):
    """pass here the soup of the page (after choosing the right package amount) and it will locate the regular and the sales price.
    Sales price could be None"""

    # without sales price => regular ----  <span data-product-price-without-tax="" class="price price--withoutTax price--main">$4.89</span>

    # when sales price present => regular ---- <span data-product-non-sale-price-without-tax="" class="price price--non-sale">$13.49</span>

    check_if_sales_price_is_present = soup.select_one('span.price.price--non-sale')

    regular_price = None
    sales_price = None

    if check_if_sales_price_is_present:
        regular_price = soup.select_one('span.price.price--non-sale').text.strip()
        sales_price = soup.select_one('span.price.price--withoutTax.price--main._hasSale').text.strip()
    else:
        regular_price = soup.select_one('span.price.price--withoutTax.price--main').text.strip()
        sales_price = None

    return {'regularPrice': regular_price, 'salesPrice': sales_price}


def extract_tier_quantity(text):
    """Get quantity from 'Buy 10' -> 10"""
    match = re.search(r'Buy (\d+)', text)
    return int(match.group(1)) if match else None


def extract_discount_info(text):
    """Get discount from '(25%)' -> '25%', True OR regular price -> price, False"""
    discount_match = re.search(r'\((\d+)%\)', text)
    if discount_match:
        return str(int(discount_match.group(1))) + '%', True
    regular_price = text.strip()
    return regular_price, False


def extract_quantity_from_name(name):
    """Get first number from product name"""
    try:
        match = re.match(r'\d+', str(name))
        return int(match.group()) if match else None
    except TypeError as e:
        print(f'Error extracting quantity: {e}')
        return None


def extract_price_amount(text):
    """Get '25.99' from '$25.99'"""
    match = re.search(r'\$(\d+\.?\d*)', text)
    return match.group(1) if match else None


def scrape_no_tiers(soup, url):
    """Handle products with no tier pricing"""
    try:
        price_elem = soup.select_one("span.price.price--withoutTax.price--main")
        if not price_elem:
            return {"regular_price": None, "tier_string": "No price found", "non_sale_price": None}

        raw_price = price_elem.text.strip()

        # Check for non-sale price
        non_sale_price = None
        if soup.select_one('span.price.price--non-sale'):
            print('Found non-sale price available')
            non_sale_price = soup.select_one('span.price.price--non-sale').text.strip()
            print(f'Non-sale price: {non_sale_price}')

        # Handle price ranges (take first price)
        try:
            regular_price = raw_price.split('-')[0].strip()
        except Exception as e:
            print(f'Price parsing error at {url}')
            traceback.print_exc()
            regular_price = raw_price

        return {
            "regular_price": regular_price,
            "tier_string": "No tiers present",
            "non_sale_price": non_sale_price
        }
    except Exception as e:
        print(f'Error in scrape_no_tiers: {e}')
        return {"regular_price": None, "tier_string": f"Error: {e}", "non_sale_price": None}


def build_tier_list(soup):
    """Extract all tier data and return list of {quantity, discount}"""
    tiers = soup.select('div.tier-button')
    tier_list = []
    regular_price = None

    for tier in tiers:
        quantity_elem = tier.select_one("div.quantity-range")
        discount_elem = tier.select_one("div.discount-info")

        if not (quantity_elem and discount_elem):
            continue

        quantity = extract_tier_quantity(quantity_elem.text)
        discount, is_discount = extract_discount_info(discount_elem.text)

        if not is_discount:
            regular_price = discount  # Store regular price for later
            continue

        if quantity and discount:
            tier_list.append({'quantity': quantity, 'discount': discount})

    return tier_list, regular_price


def get_price_for_quantity(soup, target_quantity):
    """Get specific price for a target quantity"""
    if not target_quantity:
        return None

    print(f'Looking for quantity: {target_quantity}')
    try:
        tier_button = soup.select_one(f'div.tier-button[data-min="{target_quantity}"]')
        if not tier_button:
            return None

        discount_elem = tier_button.select_one('div.discount-info')
        if not discount_elem:
            return None

        price_text = discount_elem.text
        print(f'Found price text: {price_text}')

        return extract_price_amount(price_text)
    except Exception as e:
        print(f'Error finding price for quantity {target_quantity}: {e}')
        return None


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
        tier_list, stored_regular_price = build_tier_list(soup)

        # Build tier string
        tier_string = None
        if tier_list:
            tier_string = ",".join([f"{t['quantity']}:{t['discount'].replace('%', '')}" for t in tier_list])

        # Get price for specific quantity if needed
        regular_price = stored_regular_price
        if quantity_from_excel:
            specific_price = get_price_for_quantity(soup, quantity_from_excel)
            if specific_price:
                regular_price = specific_price

        return {
            'regular_price': regular_price,
            'tier_string': tier_string
        }

    except requests.RequestException as e:
        return f"Request error: {str(e)}"
    except Exception as e:
        return f"Parsing error: {str(e)}"


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

        # Update Excel columns
        try:
            if scraped_data.get('regular_price'):
                clean_price = scraped_data['regular_price'].replace('$', '')
                df.loc[index, "PLK Regular price"] = clean_price

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


if __name__ == '__main__':
    # Uncomment to test single URL
    # test_single_url()

    # Uncomment to run full program
    input_file = "input_copy.xlsx"
    process_excel_file(input_file)