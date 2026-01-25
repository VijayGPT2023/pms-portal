"""
Analyze new Excel files to understand their structure.
"""
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

print("=" * 70)
print("SUMMARY PERFORMANCE APRIL-OCTOBER 2025 ANALYSIS")
print("=" * 70)

try:
    # Try reading with different parameters
    xl = pd.ExcelFile("Summary Performance April-October 2025.xlsx")
    print(f"Sheet names: {xl.sheet_names}")

    for sheet in xl.sheet_names[:3]:  # First 3 sheets
        print(f"\n--- Sheet: {sheet} ---")
        df = pd.read_excel(xl, sheet_name=sheet, header=None)
        print(f"Shape: {df.shape}")
        print("First 10 rows (first 15 columns):")
        for i in range(min(10, len(df))):
            row_data = [str(x)[:30] if pd.notna(x) else '' for x in df.iloc[i].values[:15]]
            print(f"Row {i}: {row_data}")
except Exception as e:
    print(f"Error: {e}")

print("\n" + "=" * 70)
print("CMR (PROGRAMME COST ESTIMATION SHEET) ANALYSIS")
print("=" * 70)

try:
    xl = pd.ExcelFile("Programme Cost Estimation Sheet CMR.xlsx")
    print(f"Sheet names: {xl.sheet_names}")

    for sheet in xl.sheet_names[:2]:  # First 2 sheets
        print(f"\n--- Sheet: {sheet} ---")
        df = pd.read_excel(xl, sheet_name=sheet, header=None)
        print(f"Shape: {df.shape}")
        print("First 15 rows (first 10 columns):")
        for i in range(min(15, len(df))):
            row_data = [str(x)[:25] if pd.notna(x) else '' for x in df.iloc[i].values[:10]]
            print(f"Row {i}: {row_data}")
except Exception as e:
    print(f"Error: {e}")
