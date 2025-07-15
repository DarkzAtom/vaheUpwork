import requests
from bs4 import BeautifulSoup
import re
import pandas as pd
import time
from urllib.parse import urljoin
import traceback
from dataclasses import dataclass
from typing import Optional, List, Dict, Any


@dataclass
class TierData:
    """Data class to represent a single pricing tier"""
    quantity: int
    discount_percentage: int

    def __str__(self):
        return f"{self.quantity}:{self.discount_percentage}"


@dataclass
class ProductPricing:
    """Data class to represent complete product pricing information"""
    regular_price: Optional[str] = None
    tier_string: Optional[str] = None
    non_sale_price: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error_message is None


class PriceExtractor:
    """Handles extraction of pricing information from HTML elements"""

    @staticmethod
    def extract_tier_quantity(text: str) -> Optional[int]:
        """Extract quantity number from tier text (e.g., 'Buy 10' -> 10)"""
        match = re.search(r'Buy (\d+)', text)
        return int(match.group(1)) if match else None

    @staticmethod
    def extract_discount_info(text: str) -> tuple[str, bool]:
        """
        Extract discount information from text
        Returns: (discount_value, is_discount_percentage)
        """
        # Check for percentage discount
        match = re.search(r'\((\d+)%\)', text)
        if match:
            return f"{match.group(1)}%", True

        # Otherwise it's a regular price
        return text.strip(), False

    @staticmethod
    def extract_quantity_from_name(name: str) -> Optional[int]:
        """Extract quantity from product name (first number found)"""
        try:
            match = re.match(r'\d+', str(name))
            return int(match.group()) if match else None
        except (TypeError, AttributeError):
            return None

    @staticmethod
    def extract_price_amount(text: str) -> Optional[str]:
        """Extract price amount from text (e.g., '$25.99' -> '25.99')"""
        match = re.search(r'\$(\d+\.?\d*)', text)
        return match.group(1) if match else None


class KratomScraper:
    """Main scraper class for kratom product pages"""

    def __init__(self, request_delay: float = 3.0):
        self.request_delay = request_delay
        self.price_extractor = PriceExtractor()

    def _make_request(self, url: str) -> Optional[BeautifulSoup]:
        """Make HTTP request and return BeautifulSoup object"""
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except requests.RequestException as e:
            print(f"Request error for {url}: {e}")
            return None

    def _extract_regular_price_without_tiers(self, soup: BeautifulSoup) -> ProductPricing:
        """Extract pricing when no tiers are present"""
        try:
            # Get main price
            main_price_elem = soup.select_one("span.price.price--withoutTax.price--main")
            if not main_price_elem:
                return ProductPricing(error_message="No main price found")

            regular_price_raw = main_price_elem.text.strip()

            # Handle price ranges (take first price)
            regular_price = regular_price_raw.split('-')[0].strip()

            # Check for non-sale price
            non_sale_price = None
            non_sale_elem = soup.select_one('span.price.price--non-sale')
            if non_sale_elem:
                non_sale_price = non_sale_elem.text.strip()

            return ProductPricing(
                regular_price=regular_price,
                tier_string="No tiers present",
                non_sale_price=non_sale_price
            )
        except Exception as e:
            return ProductPricing(error_message=f"Error extracting regular price: {e}")

    def _extract_tier_data(self, soup: BeautifulSoup) -> List[TierData]:
        """Extract all tier data from the page"""
        tiers_div = soup.select_one('div.tier-buttons')
        if not tiers_div:
            return []

        tier_elements = tiers_div.select('div.tier-button')
        tier_data = []

        for tier in tier_elements:
            quantity_elem = tier.select_one("div.quantity-range")
            discount_elem = tier.select_one("div.discount-info")

            if not (quantity_elem and discount_elem):
                continue

            quantity = self.price_extractor.extract_tier_quantity(quantity_elem.text)
            discount_value, is_discount = self.price_extractor.extract_discount_info(discount_elem.text)

            # Skip non-discount entries (regular prices)
            if not is_discount:
                continue

            if quantity and discount_value:
                # Extract just the number from percentage
                discount_num = int(discount_value.replace('%', ''))
                tier_data.append(TierData(quantity=quantity, discount_percentage=discount_num))

        return tier_data

    def _get_price_for_quantity(self, soup: BeautifulSoup, target_quantity: int) -> Optional[str]:
        """Get the price for a specific quantity"""
        try:
            tier_button = soup.select_one(f'div.tier-button[data-min="{target_quantity}"]')
            if not tier_button:
                return None

            discount_elem = tier_button.select_one('div.discount-info')
            if not discount_elem:
                return None

            return self.price_extractor.extract_price_amount(discount_elem.text)
        except Exception as e:
            print(f"Error getting price for quantity {target_quantity}: {e}")
            return None

    def scrape_product_pricing(self, url: str, target_quantity: Optional[int] = None) -> ProductPricing:
        """
        Scrape pricing information from a product page

        Args:
            url: Product page URL
            target_quantity: Specific quantity to get pricing for (optional)

        Returns:
            ProductPricing object with extracted data
        """
        soup = self._make_request(url)
        if not soup:
            return ProductPricing(error_message="Failed to load page")

        # Check if tiers exist
        tiers_div = soup.select_one('div.tier-buttons')
        if not tiers_div:
            return self._extract_regular_price_without_tiers(soup)

        # Extract tier data
        tier_data = self._extract_tier_data(soup)

        # Build tier string
        tier_string = None
        if tier_data:
            tier_string = ",".join(str(tier) for tier in tier_data)

        # Get regular price for target quantity if specified
        regular_price = None
        if target_quantity:
            regular_price = self._get_price_for_quantity(soup, target_quantity)

        return ProductPricing(
            regular_price=regular_price,
            tier_string=tier_string
        )


class ExcelProcessor:
    """Handles Excel file processing and data updates"""

    def __init__(self, scraper: KratomScraper):
        self.scraper = scraper

    def process_file(self, input_file: str, output_file: str = None) -> None:
        """Process Excel file and update with scraped data"""
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

            # Skip empty URLs
            if pd.isna(url) or url == '':
                self._update_row_with_error(df, index, 'No URL provided')
                continue

            # Skip non-pureleafkratom URLs
            if "pureleafkratom" not in url:
                continue

            print(f"Processing row {index + 1}: {url}")

            # Extract quantity from name column
            quantity = None
            if 'Name' in df.columns:
                quantity = PriceExtractor.extract_quantity_from_name(row['Name'])

            # Scrape the data
            pricing_data = self.scraper.scrape_product_pricing(url, quantity)

            # Update DataFrame
            self._update_row_with_data(df, index, pricing_data)

            # Print results
            print(f"  Regular Price: {pricing_data.regular_price}")
            print(f"  Tier String: {pricing_data.tier_string}")

            # Delay between requests
            time.sleep(self.scraper.request_delay)

        # Save results
        df.to_excel(output_file, index=False)
        print(f"\nResults saved to: {output_file}")

    def _update_row_with_error(self, df: pd.DataFrame, index: int, error_message: str) -> None:
        """Update row with error message"""
        df.loc[index, "PLK Regular price"] = error_message
        df.loc[index, "PLK Percentage Tiered Prices"] = error_message

    def _update_row_with_data(self, df: pd.DataFrame, index: int, pricing_data: ProductPricing) -> None:
        """Update row with scraped pricing data"""
        try:
            if pricing_data.regular_price:
                # Remove $ symbol if present
                clean_price = pricing_data.regular_price.replace('$', '')
                df.loc[index, "PLK Regular price"] = clean_price

            df.loc[index, "PLK Percentage Tiered Prices"] = pricing_data.tier_string

        except Exception as e:
            print(f'Error updating row {index}: {e}')
            traceback.print_exc()
            self._update_row_with_error(df, index, f"Processing error: {e}")


def test_single_url():
    """Test with a single URL"""
    url = "https://pureleafkratom.com/products/7ohmz-kratom-7-hydroxymitragynine-extract-tablets-14mg.html"

    scraper = KratomScraper()
    result = scraper.scrape_product_pricing(url)

    print(f"Testing URL: {url}")
    print(f"Regular Price: {result.regular_price}")
    print(f"Tier String: {result.tier_string}")
    print(f"Error: {result.error_message}")


def main():
    """Main function to run the scraper"""
    # Create scraper instance
    scraper = KratomScraper(request_delay=3.0)

    # Create processor instance
    processor = ExcelProcessor(scraper)

    # Process the Excel file
    input_file = "input_copy.xlsx"
    processor.process_file(input_file)


if __name__ == '__main__':
    # Uncomment to test with single URL
    # test_single_url()

    # Uncomment to run the full program
    main()