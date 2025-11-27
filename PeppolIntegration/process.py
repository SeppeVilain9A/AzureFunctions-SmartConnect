import pandas as pd
import requests
import logging
import os
from typing import Dict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_csv_file(filepath: str) -> pd.DataFrame:
    """Load CSV file into pandas DataFrame with proper delimiter handling"""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")
    
    try:
        # Read CSV with semicolon delimiter
        df = pd.read_csv(filepath, sep=';', encoding='utf-8')
        
        # Clean column names - remove quotes if present
        df.columns = df.columns.str.strip('"')
        
        logger.info(f"Successfully loaded {filepath}")
        logger.info(f"Columns found: {df.columns.tolist()}")
        logger.info(f"Number of rows: {len(df)}")
        
        return df
    except Exception as e:
        logger.error(f"Error loading {filepath}: {str(e)}")
        raise

def get_primary_address(party_id: str, postal_addresses_df: pd.DataFrame) -> str:
    """Get primary address location ID for a party"""
    primary_address = postal_addresses_df[
        (postal_addresses_df['PARTYNUMBER'] == party_id) & 
        (postal_addresses_df['ISPRIMARY'] == True)
    ]
    return primary_address['LOCATIONID'].iloc[0] if not primary_address.empty else None

def process_vat_numbers(customers_df: pd.DataFrame, 
                       registrations_df: pd.DataFrame, 
                       postal_addresses_df: pd.DataFrame) -> pd.DataFrame:
    """Process VAT numbers according to business rules"""
    results = []
    
    for _, customer in customers_df.iterrows():
        party_id = customer['PARTYNUMBER']
        customer_account = customer['CUSTOMERACCOUNT']
        vat_number = customer.get('TAXEXEMPTNUMBER')
        
        # If VAT number exists in customer record, use it
        if pd.notna(vat_number):
            results.append({
                'customerAccount': customer_account,
                'vatNumber': vat_number
            })
            continue
            
        # Find registration numbers for this party
        party_registrations = registrations_df[
            (registrations_df['PARTYNUMBER'] == party_id) & 
            (registrations_df['TAXREGSTRATIONTYPE'] == 'VAT')
        ]
        
        if party_registrations.empty:
            results.append({
                'customerAccount': customer_account,
                'vatNumber': ''
            })
            continue
            
        if len(party_registrations) == 1:
            results.append({
                'customerAccount': customer_account,
                'vatNumber': party_registrations['Registration number'].iloc[0]
            })
            continue
            
        # Multiple VAT numbers found - apply rules
        primary_location = get_primary_address(party_id, postal_addresses_df)
        
        # First try to match primary address
        primary_vat_reg = party_registrations[
            party_registrations['LOCATIONID'] == primary_location
        ]
        
        if not primary_vat_reg.empty:
            results.append({
                'customerAccount': customer_account,
                'vatNumber': primary_vat_reg['Registration number'].iloc[0]
            })
            continue
            
        # Then prefer non-enterprise VAT
        non_enterprise_vat = party_registrations[
            party_registrations['TAXREGSTRATIONTYPE'] != 'ENTERPRISE'
        ]
        
        vat_number = (non_enterprise_vat['Registration number'].iloc[0] 
                     if not non_enterprise_vat.empty 
                     else party_registrations['Registration number'].iloc[0])
        
        results.append({
            'customerAccount': customer_account,
            'vatNumber': vat_number
        })
        
    return pd.DataFrame(results)

def get_peppol_info(vat_number: str, is_test: bool = False) -> Dict:
    """Query Peppol directory API for participant info"""
    base_url = "https://test-directory.peppol.eu" if is_test else "https://directory.peppol.eu"
    endpoint = f"{base_url}/search/1.0/json?q={vat_number}"
    
    try:
        response = requests.get(endpoint)

        if response.status_code == 200:
            data = response.json()
            participantId = data["matches"][0]["participantID"]["value"]
            [peppolType,peppolId] = participantId.split(':')
            return {
                'scheme_id': peppolType,
                'peppol_id': peppolId
            }
    except Exception as e:
        logger.warning(f"Error querying Peppol API for {vat_number}: {str(e)}")
    
    return {'scheme_id': '', 'peppol_id': ''}

def main():
    """Main function for testing"""
    try:
        logger.info("Starting processing...")
        
        # Load input CSV files
        customers_df = load_csv_file('InputFolder/export VAT-Customers V3..csv')
        registrations_df = load_csv_file('InputFolder/export VAT-Registration numbers..csv')
        postal_addresses_df = load_csv_file('InputFolder/export VAT-Party postal address V2..csv')
        
        # Process VAT numbers
        logger.info("Processing VAT numbers...")
        result_df = process_vat_numbers(customers_df, registrations_df, postal_addresses_df)
        
        # Add Peppol directory information
        logger.info("Adding Peppol directory information...")
        result_df[['test_scheme_id', 'test_peppol_id', 
                  'live_scheme_id', 'live_peppol_id']] = ''
        
        for idx, row in result_df.iterrows():
            if row['vatNumber']:
                # Get test directory info
                test_info = get_peppol_info(row['vatNumber'], is_test=True)
                result_df.at[idx, 'test_scheme_id'] = test_info['scheme_id']
                result_df.at[idx, 'test_peppol_id'] = test_info['peppol_id']
                
                # Get live directory info
                live_info = get_peppol_info(row['vatNumber'], is_test=False)
                result_df.at[idx, 'live_scheme_id'] = live_info['scheme_id']
                result_df.at[idx, 'live_peppol_id'] = live_info['peppol_id']
        
        # Save results to CSV
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "processed_customers.csv")
        result_df.to_csv(output_path, index=False)
        logger.info(f"Results saved to {output_path}")
        
    except Exception as e:
        logger.error(f"Error processing data: {str(e)}")
        raise

if __name__ == "__main__":
    main()