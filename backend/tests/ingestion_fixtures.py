"""Builds small, realistic .xlsx fixtures in-memory for ingestion tests --
never committed as binary files, so diffs stay readable. Header shapes and
representative row values are taken directly from inspecting the real
Killer/Pepe sample files during Day 0, not invented.
"""

import io
from datetime import date

from openpyxl import Workbook

KILLER_HEADERS = [
    "INVOICE\nDATE",
    "NEW DATE",
    "MONTH",
    "BILL NO \nINVOICE NO",
    "PARTY NAME \n(AS PER STORE SIGNAGE)",
    "NAME",
    "STORE CODE",
    "BRAND",
    "REPORT STATUS",
    "STORE \nSTATUS",
    "TYPE",
    "ZONE",
    "CITY",
    "STATE",
    "DISTRIBUTOR \nNAME \nNEW",
    "ASM / RSM",
    "EAN CODE",
    "NEW EAN CODE",
    "MAIN\nCATEGORY",
    "ITEM NAME",
    "CATEGORY",
    "SHADE",
    "SIZE",
    "SEASON",
    "MRP",
    "FIT",
    "PRINT TYPE",
    "CLSNG \nQTY",
    "CLSNG \nVALUE",
    "QTY \nSALE",
    "NET \nSALE \nVALUE",
    "DISCOUNT \nVALUE",
    "MRP \nSALE \nVALUE",
    "F. YEAR",
]

PEPE_HEADERS = [
    "Store Name",
    "CITY",
    "STORE CODE",
    "L2L / ANULIZED",
    "Counter Types",
    "BA Name",
    "MONTH",
    "QUARTERS",
    "DATE",
    "BillNo",
    "STOCKNo",
    "PC9",
    "Size",
    "MRP",
    "Units",
    "Total MRP",
    "Net Sale Price",
    "Actual Disc",
    "WAD",
    "GENDER",
    "GEN - CAT",
    "CATEGORY",
    "FIT",
    "COLOR",
    "SEASON",
    "WEARHOUSE",
    "ATV-GWP-EOSS-Fresh",
    "Remarks (Offer/Fresh)",
]


def build_workbook(headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h) for h in headers])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def killer_workbook(rows):
    return build_workbook(KILLER_HEADERS, rows)


def pepe_workbook(rows):
    return build_workbook(PEPE_HEADERS, rows)


# Real store/product identity, real category/color/season vocabulary, taken
# from the actual Killer file. MRP/NET/DISCOUNT on row 1 are set to exactly
# match the brief's mandated sanity check (MRP 2499, Net 2124, discount 375,
# ~15%), not the literal real row (which had a different discount).
KILLER_GOOD_ROWS = [
    {
        "NEW DATE": date(2023, 4, 5),
        "MONTH": "APRIL",
        "BILL NO \nINVOICE NO": 81,
        "NAME": "AADARSH ENTERPRISES - DUMRAO",
        "STORE CODE": "ESIS170",
        "CITY": "DUMRAO",
        "STATE": "BIHAR",
        "ZONE": "EAST",
        "NEW EAN CODE": 8905646454137,
        "MAIN\nCATEGORY": "SHIRTS",
        "ITEM NAME": "1929-FS CANDY K071FSSLNDR PNK",
        "CATEGORY": "SHIRTS",
        "SHADE": "PINK",
        "SIZE": "L",
        "SEASON": "SS23",
        "MRP": 2499,
        "FIT": "KS-071 F/S SLENDER FIT",
        "PRINT TYPE": "SOLID",
        "QTY \nSALE": 1,
        "NET \nSALE \nVALUE": 2124,
        "DISCOUNT \nVALUE": 375,
        "MRP \nSALE \nVALUE": 2499,
        "F. YEAR": "23-24",
        "REPORT STATUS": "RECEIVED",  # always-unmapped in practice -> extra
    },
    {
        "NEW DATE": date(2023, 4, 26),
        "MONTH": "APRIL",
        "BILL NO \nINVOICE NO": 280,
        "NAME": "AADARSH ENTERPRISES - DUMRAO",
        "STORE CODE": "ESIS170",
        "CITY": "DUMRAO",
        "STATE": "BIHAR",
        "ZONE": "EAST",
        "NEW EAN CODE": 8905533435485,
        "MAIN\nCATEGORY": "JEANS",
        "ITEM NAME": "9507-SLM- SLMFT LGHTBL",
        "CATEGORY": "JEANS",
        "SHADE": "LIGHT BLUE",
        "SIZE": 32,  # real files mix numeric jeans sizes with text sizes
        "SEASON": "AW22",
        "MRP": 3099,
        "FIT": "SLIM FIT",
        "PRINT TYPE": "(NIL)",
        "QTY \nSALE": 1,
        "NET \nSALE \nVALUE": 2450,
        "DISCOUNT \nVALUE": 649,
        "MRP \nSALE \nVALUE": 3099,
        "F. YEAR": "23-24",
    },
    {
        # Real return row shape: quantity/mrp/net/discount all negative,
        # unit MRP stays positive (confirmed against the real file, Day 0).
        "NEW DATE": date(2023, 4, 15),
        "MONTH": "APRIL",
        "BILL NO \nINVOICE NO": 417,
        "NAME": "AADARSH ENTERPRISES - DUMRAO",
        "STORE CODE": "ESIS170",
        "CITY": "DUMRAO",
        "STATE": "BIHAR",
        "ZONE": "EAST",
        "NEW EAN CODE": 8905646462859,
        "MAIN\nCATEGORY": "SHIRTS",
        "ITEM NAME": "2001-FS SLOT K071FSSLNDR WT",
        "CATEGORY": "SHIRTS",
        "SHADE": "WHITE",
        "SIZE": "S",
        "SEASON": "SS23",
        "MRP": 1899,
        "FIT": "KS-071 F/S SLENDER FIT",
        "PRINT TYPE": "CHECKS",
        "QTY \nSALE": -1,
        "NET \nSALE \nVALUE": -1519,
        "DISCOUNT \nVALUE": -380,
        "MRP \nSALE \nVALUE": -1899,
        "F. YEAR": "23-24",
    },
]

# One deliberate error each: missing barcode, zero quantity, sign mismatch,
# unparseable date -- proving the error report is precise, not just "failed".
KILLER_BAD_ROWS = [
    {
        **KILLER_GOOD_ROWS[0],
        "BILL NO \nINVOICE NO": 82,
        "NEW EAN CODE": None,  # required field missing
    },
    {
        **KILLER_GOOD_ROWS[0],
        "BILL NO \nINVOICE NO": 83,
        "QTY \nSALE": 0,  # zero-quantity / GWP-style row, rejected in Phase 1
    },
    {
        **KILLER_GOOD_ROWS[0],
        "BILL NO \nINVOICE NO": 84,
        "QTY \nSALE": 1,
        "NET \nSALE \nVALUE": -2124,  # sign mismatch: positive qty, negative net
    },
    {
        **KILLER_GOOD_ROWS[0],
        "BILL NO \nINVOICE NO": 85,
        "NEW DATE": "not-a-date",
    },
]

# Spans 2 financial years / 3 calendar months / 3 seasons / 2 categories /
# 2 stores so trend math (YoY, MoM, Season-by-Season) and store/category
# scoping have something real to group and order by. F. YEAR is left
# consistent with each NEW DATE's fiscal year (Apr-Mar) since the MVs derive
# financial_year from dim_calendar via sale_date, not from this column
# (Killer's F. YEAR is trusted-as-supplied and only lands on fact_sales for
# audit) -- but a mismatched value here would silently mask a real bug, so
# it's kept accurate.
KILLER_TREND_ROWS = [
    {
        **KILLER_GOOD_ROWS[0],
        "BILL NO \nINVOICE NO": 501,
        "NEW DATE": date(2023, 4, 5),
        "MONTH": "APRIL",
        "F. YEAR": "23-24",
        "CATEGORY": "SHIRTS",
        "MAIN\nCATEGORY": "SHIRTS",
        "SEASON": "SS23",
        "MRP": 1000,
        "QTY \nSALE": 1,
        "NET \nSALE \nVALUE": 1000,
        "DISCOUNT \nVALUE": 0,
        "MRP \nSALE \nVALUE": 1000,
    },
    {
        **KILLER_GOOD_ROWS[0],
        "BILL NO \nINVOICE NO": 502,
        "NEW DATE": date(2023, 7, 10),
        "MONTH": "JULY",
        "F. YEAR": "23-24",
        "CATEGORY": "SHIRTS",
        "MAIN\nCATEGORY": "SHIRTS",
        "SEASON": "SS23",
        "MRP": 2000,
        "QTY \nSALE": 1,
        "NET \nSALE \nVALUE": 1800,
        "DISCOUNT \nVALUE": 200,
        "MRP \nSALE \nVALUE": 2000,
    },
    {
        **KILLER_GOOD_ROWS[0],
        "BILL NO \nINVOICE NO": 503,
        "NEW EAN CODE": 8905533435485,
        "NEW DATE": date(2023, 10, 15),
        "MONTH": "OCTOBER",
        "F. YEAR": "23-24",
        "CATEGORY": "JEANS",
        "MAIN\nCATEGORY": "JEANS",
        "SEASON": "AW23",
        "MRP": 750,
        "QTY \nSALE": 2,
        "NET \nSALE \nVALUE": 1500,
        "DISCOUNT \nVALUE": 0,
        "MRP \nSALE \nVALUE": 1500,
    },
    {
        **KILLER_GOOD_ROWS[0],
        "BILL NO \nINVOICE NO": 504,
        "NEW DATE": date(2024, 4, 20),
        "MONTH": "APRIL",
        "F. YEAR": "24-25",
        "CATEGORY": "SHIRTS",
        "MAIN\nCATEGORY": "SHIRTS",
        "SEASON": "SS24",
        "MRP": 3000,
        "QTY \nSALE": 1,
        "NET \nSALE \nVALUE": 3000,
        "DISCOUNT \nVALUE": 0,
        "MRP \nSALE \nVALUE": 3000,
    },
    {
        # Different store -- proves store_trend's store_code scoping
        # actually filters, not just happens to match everything.
        **KILLER_GOOD_ROWS[0],
        "BILL NO \nINVOICE NO": 505,
        "NEW DATE": date(2023, 4, 5),
        "MONTH": "APRIL",
        "F. YEAR": "23-24",
        "STORE CODE": "ESIS999",
        "CATEGORY": "SHIRTS",
        "MAIN\nCATEGORY": "SHIRTS",
        "SEASON": "SS23",
        "MRP": 500,
        "QTY \nSALE": 1,
        "NET \nSALE \nVALUE": 500,
        "DISCOUNT \nVALUE": 0,
        "MRP \nSALE \nVALUE": 500,
    },
]

PEPE_GOOD_ROWS = [
    {
        "Store Name": "THE BIG SHOP - PURNEA",
        "CITY": "PURNEA",
        "STORE CODE": "SI-032",
        "MONTH": "JANUARY- 2026",
        "QUARTERS": "Q- 4",
        "DATE": date(2026, 1, 15),
        "BillNo": "PRHO26-79718",
        "STOCKNo": 8905875293118,
        "PC9": "PM308998",
        "Size": "M",
        "MRP": 2999,
        "Units": 1,
        "Total MRP": 2999,
        "Net Sale Price": 1799,
        "Actual Disc": 1200,
        "WAD": 0.40,  # matches computed discount% exactly (brief's sanity check)
        "GENDER": "MENS",
        "GEN - CAT": "TOP WEAR",
        "CATEGORY": "SHIRTS",
        "FIT": "REGULAR",
        "COLOR": "WHITE",
        "SEASON": "FASHION BASICS",
    },
    {
        "Store Name": "THE BIG SHOP - PURNEA",
        "CITY": "PURNEA",
        "STORE CODE": "SI-032",
        "MONTH": "APRIL- 2026",  # different month -- real files span several
        "QUARTERS": "Q- 1",
        "DATE": date(2026, 4, 3),
        "BillNo": "PRHON26-8583",
        "STOCKNo": 8905875558521,
        "PC9": "PM3091063",
        "Size": "M",
        "MRP": 2799,
        "Units": 1,
        "Total MRP": 2799,
        "Net Sale Price": 2519,
        "Actual Disc": 280,
        "WAD": 0.1000357270453734,
        "GENDER": "MENS",
        "GEN - CAT": "TOP WEAR",
        "CATEGORY": "SHIRTS",
        "FIT": "REGULAR",
        "COLOR": "OLIVE GREEN",
        "SEASON": "AW25",
    },
    {
        # Real return row shape (Day 0 finding): all negative together.
        "Store Name": "CHANDA MAMA - HAJIPUR",
        "CITY": "HAJIPUR",
        "STORE CODE": "SI-008",
        "MONTH": "JANUARY- 2026",
        "QUARTERS": "Q- 4",
        "DATE": date(2026, 1, 24),
        "BillNo": "0101N-019614",
        "STOCKNo": 8905875451341,
        "PC9": "PM3090959",
        "Size": "XXL",
        "MRP": 3499,
        "Units": -1,
        "Total MRP": -3499,
        "Net Sale Price": -2099.03,
        "Actual Disc": -1399.97,
        "WAD": 0.4001057444984281,
        "GENDER": "MENS",
        "GEN - CAT": "TOP WEAR",
        "CATEGORY": "SHIRTS",
        "FIT": "REGULAR",
        "COLOR": "DARK GREEN",
        "SEASON": "AW25",
    },
]

PEPE_BAD_ROWS = [
    {
        **PEPE_GOOD_ROWS[0],
        "BillNo": "PRHO26-79719",
        "STOCKNo": None,  # required field missing
    },
    {
        **PEPE_GOOD_ROWS[0],
        "BillNo": "PRHO26-79720",
        "Units": 0,  # zero-quantity / GWP-style row
    },
    {
        **PEPE_GOOD_ROWS[0],
        "BillNo": "PRHO26-79721",
        "WAD": 0.90,  # supplied discount% wildly disagrees with computed 40%
    },
]
