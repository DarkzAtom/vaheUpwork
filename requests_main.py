import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
import time
from urllib.parse import urljoin
import traceback


def extract_tier_number(line):
    match = re.search(r'Buy (\d+)', line)
    if match:
        return int(match.group(1))
    return None


def extract_discount_per_tier(line):
    match = re.search(r'\((\d+)%\)', line)
    if match:
        is_discount = True
        return_string = (str(int(match.group(1))) + '%')
        return return_string, is_discount
    is_discount = False
    regular_price = line.strip()
    return regular_price, is_discount


def extract_quantity_number_from_the_name_column_at_the_beginning(raw_value):
    try:
        match = re.match(r'\d+', raw_value)
        processed_value = int(match.group()) if match else None
        return processed_value
    except TypeError as e:
        print(f'line 34 error {e}')
        return None

def scrape_tier_data(url, quantity_from_excel):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        tiers_div = soup.select_one('div.tier-buttons')
        if not tiers_div:
            regular_price_unprocessed = soup.select_one("span.price.price--withoutTax.price--main").text.strip()
            non_sale_price = None
            if soup.select_one('span.price.price--non-sale'):
                print('line 48: there IS a non-sale price available')
                non_sale_price = soup.select_one('span.price.price--non-sale').text.strip()
            try:
                regular_price = regular_price_unprocessed.split('-')[0].strip()
            except Exception as e:
                print(f'error at {url}')
                print(f'Full traceback:')
                traceback.print_exc()
                regular_price = regular_price_unprocessed
            return {"regular_price": regular_price, "tier_string": "No tiers present", "non_sale_price": non_sale_price}

        tiers = tiers_div.select('div.tier-button')

        list_of_dict_of_tiers = []

        regular_price = None

        for tier in tiers:
            quantity_elem = tier.select_one("div.quantity-range")
            discount_elem = tier.select_one("div.discount-info")

            if quantity_elem and discount_elem:
                quantity_unprocessed = quantity_elem.text
                discount_unprocessed = discount_elem.text

                quantity = extract_tier_number(quantity_unprocessed)
                discount, is_discount = extract_discount_per_tier(discount_unprocessed)

                if not is_discount:
                    regular_price = discount
                    continue

                if quantity and discount:
                    dict_to_append = {
                        'quantity': quantity,
                        'discount': discount
                    }

                    list_of_dict_of_tiers.append(dict_to_append)



        if list_of_dict_of_tiers:
            tier_string = ",".join(
                [f"{tier['quantity']}:{tier['discount'].replace('%', '')}" for tier in list_of_dict_of_tiers])

            if quantity_from_excel:
                print(f'quantity: {quantity_from_excel}')
                try:
                    regular_price_external_container = soup.select_one(f'div.tier-button[data-min="{quantity_from_excel}"]')
                    regular_price_unprocessed = regular_price_external_container.select_one('div.discount-info').text
                    print(f'regular_price_unprocessed: {regular_price_unprocessed}')
                    amount = re.search(r'\$(\d+\.?\d*)', regular_price_unprocessed)
                    regular_price = amount.group(1) if amount else None
                except Exception as e:
                    print('94 line error find quantity container')

            return {'regular_price': regular_price, 'tier_string': tier_string}
        else:
            if quantity_from_excel:
                print(f'quantity: {quantity_from_excel}')
                try:
                    regular_price_external_container = soup.select_one(f'div.tier-button[data-min="{quantity_from_excel}"]')
                    regular_price_unprocessed = regular_price_external_container.select_one('div.discount-info').text
                    amount = re.search(r'\$(\d+\.?\d*)', regular_price_unprocessed)
                    regular_price = amount.group(1) if amount else None
                except Exception as e:
                    print('102 line error find quantity container')
            return {'regular_price': regular_price, 'tier_string': None}
    except requests.RequestException as e:
        return f"Requests error: {str(e)}"
    except Exception as e:
        return f"Parsing error: {str(e)}"



def process_excel_file(input_file, output_file=None):
    if output_file is None:
        output_file = input_file.replace('.xlsx', '_processed.xlsx')

    #reading the Excel file logic

    try:
        df = pd.read_excel(input_file)
    except Exception as e:
        print(f'Error reading Excel file: {e}')
        return

    print(f"Processing {len(df)} URLs...")

    # processing each URL

    for index, row in df.iterrows():
        url = row.iloc[0]

        quantity = extract_quantity_number_from_the_name_column_at_the_beginning(row.loc['Name'])

        print(f'quan: {quantity}, indx {index}')


        if pd.isna(url) or url == '':
            df.iloc[index, 8] = 'No URL provided'
            df.iloc[index, 9] = 'No URL provided'
            continue

        if not "pureleafkratom" in url:
            continue

        print(f"Processing row {int(index) + 1}: {url}")

        #scrapin the data

        scraped_data = scrape_tier_data(url, quantity)

        try:
            df.loc[index, "PLK Regular price"] = scraped_data['regular_price'].replace('$', '')  # this is column I --- regular price

            df.loc[index, "PLK Percentage Tiered Prices"] = scraped_data['tier_string']  # this is column J -- tiers and discounts
        except Exception as e:
            print(f'problematic {url} exception: {e}')
            print(f'Full traceback:')
            traceback.print_exc()
            continue

        print(f"Regular Price: {scraped_data['regular_price']}")
        print(f"Tier string: {scraped_data['tier_string']}")

        time.sleep(3)

    df.to_excel(output_file, index=False)
    print(f"\nResults saved to: {output_file}")


def test_single_url():
    """herre we  have the single url for test, the one url you sent to me in upwork messages"""
    url = "https://pureleafkratom.com/products/7ohmz-kratom-7-hydroxymitragynine-extract-tablets-14mg.html"
    print(f"Testing URL: {url}")
    result = scrape_tier_data(url)
    print(f"Regular Price: {result['regular_price']}")
    print(f"Tier String: {result['tier_string']}")

if __name__ == '__main__':
    # uncomment the following below to test with the single url
    # test_single_url()

    # uncomment the following below to actually run the program with the excel file
    input_file = "input_copy.xlsx"  # Change this to your Excel file path
    process_excel_file(input_file)