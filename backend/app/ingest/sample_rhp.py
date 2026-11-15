"""Generates a FICTIONAL, SEBI-style Red Herring Prospectus PDF for demos and tests.

The company, promoters, peers and every number are invented. The layout mimics real offer
documents (cover page, table of contents, risk factors, objects of the offer, peer comparison,
restated financial summary with a part-year column, litigation summary) so the extractor can be
exercised end to end without downloading anything.
"""
from __future__ import annotations

from pathlib import Path

RUPEE_FONT = Path("C:/Windows/Fonts/arial.ttf")


def build_sample_rhp() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    has_font = RUPEE_FONT.exists()
    R = "₹" if has_font else "Rs."

    def page():
        p = doc.new_page(width=595, height=842)
        if has_font:
            p.insert_font(fontname="arial", fontfile=str(RUPEE_FONT))
        return p

    def text(p, x, y, s, size=9.5, bold=False):
        p.insert_text((x, y), s, fontsize=size, fontname="arial" if has_font else ("helv" if not bold else "hebo"))

    def para(p, y, s, size=9.5, width=470):
        rect = pymupdf.Rect(60, y, 60 + width, y + 400)
        p.insert_textbox(rect, s, fontsize=size, fontname="arial" if has_font else "helv")

    def table(p, y, cols, rows, size=8.5):
        for r, row in enumerate(rows):
            for x, cell in zip(cols, row):
                text(p, x, y + r * 16, cell, size)

    # 1. Cover
    p = page()
    text(p, 60, 60, "RED HERRING PROSPECTUS", 12)
    text(p, 60, 76, "Dated October 20, 2026  |  100% Book Built Offer", 9)
    text(p, 60, 110, "DEMO PRECISION COMPONENTS LIMITED", 16)
    text(p, 60, 128, "SAMPLE DOCUMENT: FICTIONAL COMPANY CREATED FOR DEMONSTRATION. NOT A REAL OFFER.", 8)
    text(p, 60, 150, "OUR PROMOTERS: A. SAMPLE AND B. EXAMPLE", 9)
    para(p, 170, (
        f"INITIAL PUBLIC OFFERING OF UP TO 2,29,35,780 EQUITY SHARES OF FACE VALUE OF {R} 2 EACH OF DEMO PRECISION "
        f"COMPONENTS LIMITED COMPRISING A FRESH ISSUE OF UP TO 91,74,312 EQUITY SHARES OF FACE VALUE OF {R} 2 EACH "
        f"AGGREGATING UP TO {R} 4,000.00 MILLION AND AN OFFER FOR SALE OF UP TO 1,37,61,468 EQUITY SHARES OF FACE "
        f"VALUE OF {R} 2 EACH AGGREGATING UP TO {R} 6,000.00 MILLION BY THE SELLING SHAREHOLDERS."))
    text(p, 60, 270, f"PRICE BAND: {R} 415 TO {R} 436 PER EQUITY SHARE OF FACE VALUE OF {R} 2 EACH", 10)
    para(p, 285, "BIDS CAN BE MADE FOR A MINIMUM OF 34 EQUITY SHARES AND IN MULTIPLES OF 34 EQUITY SHARES THEREAFTER.")
    text(p, 60, 330, "BID/OFFER OPENS ON: MONDAY, NOVEMBER 2, 2026", 10)
    text(p, 60, 346, "BID/OFFER CLOSES ON: WEDNESDAY, NOVEMBER 4, 2026", 10)
    text(p, 60, 380, "BOOK RUNNING LEAD MANAGER: SAMPLE CAPITAL MARKETS LIMITED", 8.5)
    text(p, 60, 394, "REGISTRAR TO THE OFFER: DEMO REGISTRY PRIVATE LIMITED", 8.5)

    # 2. Table of contents
    p = page()
    text(p, 60, 60, "TABLE OF CONTENTS", 12)
    for k, (s, n) in enumerate([("SUMMARY OF THE OFFER DOCUMENT", 3), ("RISK FACTORS", 4), ("CAPITAL STRUCTURE", 5),
                                ("OBJECTS OF THE OFFER", 6), ("BASIS FOR OFFER PRICE", 7), ("OUR BUSINESS", 8),
                                ("SUMMARY OF RESTATED FINANCIAL INFORMATION", 9), ("OUTSTANDING LITIGATION", 10)]):
        text(p, 60, 90 + k * 16, f"{s} " + "." * 40 + f" {n}", 9)

    # 3. Summary of the offer document
    p = page()
    text(p, 60, 60, "SUMMARY OF THE OFFER DOCUMENT", 12)
    para(p, 80, (
        "Our Company is a manufacturer of precision-machined components for passenger-vehicle and two-wheeler OEMs, "
        "operating four plants. The aggregate pre-Offer shareholding of our Promoters and Promoter Group is 88.00% of "
        "the pre-Offer paid-up Equity Share capital. The post-Offer shareholding of our Promoters and Promoter Group "
        f"will be 68.88% of the post-Offer paid-up Equity Share capital. As of June 30, 2026, our contingent liabilities, "
        f"as per the Restated Financial Information, aggregated to {R} 450.00 million."))

    # 4. Risk factors
    p = page()
    text(p, 60, 60, "SECTION II - RISK FACTORS", 12)
    text(p, 60, 84, "Internal Risk Factors", 10)
    risks = [
        "1. Our top five customers contributed 58.20% of our revenue from operations in Fiscal 2026, and the loss of",
        "any of them could adversely affect our business.",
        "",
        "2. We depend on the domestic passenger-vehicle cycle; a slowdown in vehicle demand would reduce our sales.",
        "",
        "3. Prices of steel and aluminium are volatile and we may not be able to pass on cost increases to customers.",
        "",
        "4. Our operating cash flows were lower than our profits in certain periods because of rising receivables.",
        "",
        "5. Some of our Promoters are selling Equity Shares in the Offer and will not receive any proceeds for us.",
        "",
        "6. There are outstanding legal proceedings involving our Company and our Promoters.",
    ]
    for k, ln in enumerate(risks):
        text(p, 60, 104 + k * 14, ln, 9)
    para(p, 300, "This page is part of the fictional sample document. " * 12, 8)

    # 5. Capital structure
    p = page()
    text(p, 60, 60, "CAPITAL STRUCTURE", 12)
    para(p, 80, (f"Issued, subscribed and paid-up share capital before the Offer: 10,50,00,000 Equity Shares of face "
                 f"value of {R} 2 each. Issued, subscribed and paid-up share capital after the Offer: 11,41,74,312 Equity "
                 f"Shares of face value of {R} 2 each."))

    # 6. Objects of the offer
    p = page()
    text(p, 60, 60, "OBJECTS OF THE OFFER", 12)
    para(p, 80, "The Net Proceeds are proposed to be utilised in the following manner:", 9)
    text(p, 400, 112, f"({R} in million)", 8.5)
    table(p, 130, [60, 420], [["Particulars", "Estimated amount"],
                              ["Repayment/prepayment of certain outstanding borrowings", "1,800.00"],
                              ["Funding capital expenditure towards a new plant at Pune", "1,400.00"],
                              ["General corporate purposes(1)", "800.00"],
                              ["Total", "4,000.00"]])
    para(p, 230, "This page is part of the fictional sample document. " * 10, 8)

    # 7. Basis for offer price (peer comparison)
    p = page()
    text(p, 60, 60, "BASIS FOR OFFER PRICE", 12)
    text(p, 60, 84, "Comparison of accounting ratios with listed industry peers", 10)
    cols = [40, 210, 265, 330, 375, 430, 480]
    table(p, 108, cols, [
        ["Name of the company", "Face value", "Closing price", "P/E", "EPS Basic", "RoNW (%)", "NAV per share"],
        ["Demo Precision Components Limited", "2", "NA", "NA", "13.22", "17.16", "83.81"],
        ["Sample Auto Parts Limited", "2", "640.00", "32.00", "20.00", "16.00", "125.50"],
        ["Example Forgings Limited", "5", "520.00", "26.00", "20.00", "14.00", "133.30"],
        ["Illustrative Engineering Limited", "1", "1,230.00", "41.00", "30.00", "19.00", "170.80"],
    ])
    para(p, 200, "Source: fictional figures created for this sample document.", 8)

    # 8. Our business
    p = page()
    text(p, 60, 60, "OUR BUSINESS", 12)
    text(p, 60, 84, "Overview", 10)
    para(p, 100, (
        "We are a manufacturer of precision-machined and assembled components such as transmission parts, steering "
        "components and engine sub-assemblies, supplying passenger-vehicle and two-wheeler OEMs in India. We operate "
        "four manufacturing facilities and served 48 customers in Fiscal 2026. This description is fictional and "
        "exists only to demonstrate how Analytivest reads an offer document."))

    # 9. Summary of restated financial information
    p = page()
    text(p, 60, 60, "SUMMARY OF RESTATED FINANCIAL INFORMATION", 12)
    text(p, 430, 82, f"({R} in million)", 8.5)
    cols = [40, 250, 345, 410, 475]
    table(p, 100, cols, [
        ["Particulars", "Three months ended", "Fiscal 2026", "Fiscal 2025", "Fiscal 2024"],
        ["", "June 30, 2026", "", "", ""],
        ["Revenue from operations", "5,320.10", "20,100.00", "17,200.00", "14,500.00"],
        ["EBITDA", "830.50", "3,180.00", "2,650.00", "2,180.00"],
        ["EBITDA margin (%)", "15.61", "15.82", "15.41", "15.03"],
        ["Restated profit for the year/period", "402.20", "1,510.00", "1,240.00", "960.00"],
        ["Net worth", "9,150.00", "8,800.00", "7,350.00", "6,200.00"],
        ["Total borrowings", "5,300.00", "5,200.00", "4,550.00", "4,100.00"],
        ["Net cash generated from operating activities", "210.00", "1,460.00", "1,040.00", "1,200.00"],
        ["Purchase of property, plant and equipment", "(380.00)", "(1,600.00)", "(1,300.00)", "(950.00)"],
        ["Cash and cash equivalents", "590.00", "600.00", "410.00", "380.00"],
    ], size=8)

    # 10. Litigation
    p = page()
    text(p, 60, 60, "SUMMARY OF OUTSTANDING LITIGATION", 12)
    para(p, 84, (f"Criminal proceedings against our Company: 1. Tax proceedings involving our Company: 3, aggregate "
                 f"amount involved {R} 120.50 million. Civil proceedings against our Promoters: 1. All figures in this "
                 "fictional sample are invented."))
    return doc.tobytes()


if __name__ == "__main__":
    Path("sample_rhp.pdf").write_bytes(build_sample_rhp())
