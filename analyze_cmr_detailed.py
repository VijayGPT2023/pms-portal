"""
Detailed analysis of CMR file for expenditure heads.
"""
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

print("=" * 70)
print("CMR EXPENDITURE HEADS ANALYSIS")
print("=" * 70)

df = pd.read_excel("Programme Cost Estimation Sheet CMR.xlsx", sheet_name="Sheet2", header=None)
print(f"Total rows: {len(df)}")

# Print all rows to see expenditure structure
for i in range(len(df)):
    row_data = df.iloc[i].values
    # Only print rows with some content in first 2 columns
    if pd.notna(row_data[0]) or pd.notna(row_data[1]):
        content = [str(x)[:40] if pd.notna(x) else '' for x in row_data[:6]]
        print(f"Row {i:2d}: {content}")
