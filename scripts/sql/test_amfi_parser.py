import sys
sys.path.insert(0, '.')
from scripts.ingestion.fetch_amfi_nav import parse_amfi_historical_text
import requests

url = 'https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx'
params = {'frmdt': '01-Jun-2024', 'todt': '05-Jun-2024'}
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
r = requests.get(url, params=params, headers=headers, timeout=60)

df = parse_amfi_historical_text(r.text)
print(f"Rows   : {len(df):,}")
print(f"Funds  : {df['scheme_code'].nunique():,}")
print(f"Dates  : {df['date'].min().date()} to {df['date'].max().date()}")
print(df[['scheme_code', 'scheme_name', 'nav', 'date']].head(5).to_string(index=False))
