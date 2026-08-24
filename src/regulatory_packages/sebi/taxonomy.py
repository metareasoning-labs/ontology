"""Controlled vocabulary and title-based tagging for SEBI documents."""

from __future__ import annotations

import hashlib
import re
from typing import Literal

LegalHierarchy = Literal[
    "act",
    "regulation",
    "master_circular",
    "circular",
    "guidance_note",
    "gazette_notification",
    "rule",
    "general_order",
]

# Short entity codes used in catalog records; frontend maps to full PRD labels.
SEBI_ENTITY_CODES = [
    "Stock Brokers",
    "Portfolio Managers",
    "Mutual Funds",
    "AIF",
    "Venture Capital",
    "FPIs",
    "Custodians",
    "Merchant Bankers",
    "RTAs",
    "Debenture Trustees",
    "Credit Rating Agencies",
    "Underwriters",
    "Bankers to an Issue",
    "KYC Agencies",
    "Depositories",
    "Investment Advisers",
    "Research Analysts",
    "General",
]

SEBI_ENTITY_LABELS: dict[str, str] = {
    "Stock Brokers": "Stock Brokers (equity/derivatives/currency)",
    "Portfolio Managers": "Portfolio Managers",
    "Mutual Funds": "Mutual Funds / AMCs",
    "AIF": "Alternative Investment Funds (AIFs)",
    "Venture Capital": "Venture Capital Funds",
    "FPIs": "Foreign Portfolio Investors (FPIs)",
    "Custodians": "Custodians",
    "Merchant Bankers": "Merchant Bankers",
    "RTAs": "Registrar & Transfer Agents (RTAs)",
    "Debenture Trustees": "Debenture Trustees",
    "Credit Rating Agencies": "Credit Rating Agencies",
    "Underwriters": "Underwriters",
    "Bankers to an Issue": "Bankers to an Issue",
    "KYC Agencies": "KYC Registration Agencies",
    "Depositories": "Depositories",
    "Investment Advisers": "Investment Advisers",
    "Research Analysts": "Research Analysts",
    "General": "General / Cross-cutting",
}

SEBI_TOPICS = [
    "Registration & Licensing",
    "Governance & Fit-and-Proper Criteria",
    "Client Onboarding / KYC / Suitability",
    "Disclosure & Reporting (periodic, event-based)",
    "Risk Management & Margins",
    "Fund Structuring & Investment Restrictions",
    "Fees, Expenses & TER",
    "Valuation & NAV",
    "Settlement & Custody",
    "Insider Trading / Fraud / Market Conduct",
    "Cybersecurity & Technology",
    "Winding-up / Exit / Redemption",
    "Nomination & Investor Protection",
    "Enforcement & Penalties",
    "Cross-border / FPI-specific",
]

RELATIONSHIP_TYPES = [
    "implements",
    "amends",
    "supersedes",
    "superseded_by",
    "repeals",
    "repealed_by",
    "consolidates",
    "applies_to",
    "cross_references",
    "issued_under",
]

DOCUMENT_STATUSES = ["in_force", "superseded", "partially_amended", "under_consultation"]

HIERARCHY_BY_SECTION: dict[str, LegalHierarchy] = {
    "Acts": "act",
    "Rules": "rule",
    "Regulations": "regulation",
    "General Orders": "general_order",
    "Guidelines": "guidance_note",
    "Master Circulars": "master_circular",
    "Circulars": "circular",
    "Gazette Notifications": "gazette_notification",
}

_ENTITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AIF", re.compile(
        r"\b(aif|aifs|alternative investment fund|alternative investment funds|"
        r"category\s+[i123]{1,3}|cat\.?\s*[i123]{1,3})\b",
        re.I,
    )),
    ("Mutual Funds", re.compile(
        r"\b(mutual fund|mutual funds|\bmf\b|amc|asset management compan|"
        r"scheme\s+of\s+mutual|unit holder|unitholder|sip\b|elss\b)\b",
        re.I,
    )),
    ("Stock Brokers", re.compile(
        r"\b(stock broker|stock brokers|trading member|trading members|\btm\b|"
        r"sub-?broker|derivatives?\s+segment|commodity derivatives?|"
        r"currency derivatives?|cash market|margin trading|f&o|futures\s+and\s+options|"
        r"internet based trading|stock exchange|clearing corporation|"
        r"commodity exchange|intermediary|intermediaries|"
        r"\bmargins?\b|contract note|exchange traded derivative|peak margin|"
        r"investment limit in exchange|trading and settlement)\b",
        re.I,
    )),
    ("Portfolio Managers", re.compile(r"\b(portfolio manager|portfolio managers|\bpms\b)\b", re.I)),
    ("FPIs", re.compile(
        r"\b(fpi|fpis|foreign portfolio investor|foreign portfolio investors|"
        r"foreign institutional investor|\bfii\b|fiis)\b",
        re.I,
    )),
    ("Custodians", re.compile(r"\b(custodian|custodians|global custodian)\b", re.I)),
    ("Merchant Bankers", re.compile(
        r"\b(merchant banker|merchant bankers|lead manager|book running|"
        r"green debt|debt securities|non-convertible|offer document|prospectus|"
        r"substantial acquisition|takeover|issue of capital)\b",
        re.I,
    )),
    ("RTAs", re.compile(
        r"\b(rta|rtas|registrar|transfer agent|share transfer agent|"
        r"registrars?\s+to\s+an\s+issue)\b",
        re.I,
    )),
    ("Debenture Trustees", re.compile(r"\b(debenture trustee|debenture trustees|\bdt\b)\b", re.I)),
    ("Credit Rating Agencies", re.compile(
        r"\b(credit rating|credit rating agenc|rating agenc|\bcra\b|esg rating provider|\berp\b)\b",
        re.I,
    )),
    ("Underwriters", re.compile(r"\b(underwriter|underwriters|underwriting)\b", re.I)),
    ("Bankers to an Issue", re.compile(r"\b(banker to an issue|bankers to an issue|\bbti\b)\b", re.I)),
    ("KYC Agencies", re.compile(
        r"\b(kra|kyc registration agenc|central database of market participant|\bcdmp\b|"
        r"e-kyc|aadhaar|ckyc|pan/gir)\b",
        re.I,
    )),
    ("Depositories", re.compile(
        r"\b(depositor|depositories|demat|dematerial|nsdl|cdsl|depository participant|\bdp\b|"
        r"settlement of trades in dematerial)\b",
        re.I,
    )),
    ("Investment Advisers", re.compile(r"\b(investment adviser|investment advisor|investment advisers|\bria\b)\b", re.I)),
    ("Research Analysts", re.compile(r"\b(research analyst|research analysts|\bra\b)\b", re.I)),
    ("Venture Capital", re.compile(r"\b(venture capital|\bfvci\b|foreign venture capital|\bvcc\b)\b", re.I)),
]

# Map regulation parenthetical subject / master-circular heading fragments → entity codes.
_SUBJECT_ENTITY_RULES: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"alternative investment fund|\baif\b", re.I), ["AIF"]),
    (re.compile(r"mutual fund", re.I), ["Mutual Funds"]),
    (re.compile(r"foreign portfolio investor|\bfpi\b", re.I), ["FPIs"]),
    (re.compile(r"foreign venture capital|\bfvci\b", re.I), ["Venture Capital"]),
    (re.compile(r"portfolio manager|\bpms\b", re.I), ["Portfolio Managers"]),
    (re.compile(r"investment adviser|\binvestment advisor\b", re.I), ["Investment Advisers"]),
    (re.compile(r"research analyst", re.I), ["Research Analysts"]),
    (re.compile(r"stock broker|sub-?broker|stock brokers", re.I), ["Stock Brokers"]),
    (re.compile(r"stock exchange|clearing corporation|commodity derivatives?", re.I), ["Stock Brokers"]),
    (re.compile(r"merchant banker", re.I), ["Merchant Bankers"]),
    (re.compile(r"debenture trustee", re.I), ["Debenture Trustees"]),
    (re.compile(r"credit rating|esg rating provider", re.I), ["Credit Rating Agencies"]),
    (re.compile(r"depositor|depository participant", re.I), ["Depositories"]),
    (re.compile(r"custodian", re.I), ["Custodians"]),
    (re.compile(r"registrar|transfer agent|share transfer agent", re.I), ["RTAs"]),
    (re.compile(r"banker to an issue", re.I), ["Bankers to an Issue"]),
    (re.compile(r"underwriter", re.I), ["Underwriters"]),
    (re.compile(r"kyc registration|kra\b|central database of market participant", re.I), ["KYC Agencies"]),
    (re.compile(r"infrastructure investment trust|\binvit\b", re.I), ["AIF"]),
    (re.compile(r"real estate investment trust|\breit\b", re.I), ["AIF"]),
    (re.compile(r"issue of capital|issue and listing|\bicdr\b", re.I), ["Merchant Bankers", "Bankers to an Issue"]),
    (re.compile(r"buy-?back of securities", re.I), ["Merchant Bankers", "Stock Brokers"]),
    (re.compile(r"collective investment scheme|\bcis\b", re.I), ["Mutual Funds"]),
    (re.compile(r"substantial acquisition|takeovers?", re.I), ["Merchant Bankers"]),
    (re.compile(r"listing obligation|listing agreement|listed compan|corporate governance in listed", re.I), ["General"]),
    (re.compile(r"green debt|debt securities|non-convertible|municipal debt", re.I), ["Merchant Bankers", "Debenture Trustees"]),
    (re.compile(r"dematerial|demat", re.I), ["Depositories"]),
    (re.compile(r"\bmargins?\b|exchange traded derivative", re.I), ["Stock Brokers"]),
    (re.compile(r"index provider", re.I), ["General"]),
]

_REGULATION_IN_TITLE_RE = re.compile(
    r"sebi\s*\(([^)]+)\)\s*(?:\([^)]+\)\s*)?regulations?,?\s*(\d{4})?",
    re.I,
)
_MASTER_CIRCULAR_FOR_RE = re.compile(
    r"master\s+circular\s+for\s+(.+?)(?:\s*\(|\s*\[|\s*\.|\s*$)",
    re.I,
)

_TOPIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Registration & Licensing", re.compile(r"\b(registration|licen[cs]e|certification|empanelment)\b", re.I)),
    ("Governance & Fit-and-Proper Criteria", re.compile(r"\b(governance|fit and proper|director|board|compliance officer)\b", re.I)),
    ("Client Onboarding / KYC / Suitability", re.compile(r"\b(kyc|know your client|onboarding|suitability|client due diligence)\b", re.I)),
    ("Disclosure & Reporting (periodic, event-based)", re.compile(r"\b(disclosure|reporting|periodic|quarterly|annual report|filing)\b", re.I)),
    ("Risk Management & Margins", re.compile(r"\b(risk management|margin|leverage|exposure|stress test)\b", re.I)),
    ("Fund Structuring & Investment Restrictions", re.compile(r"\b(investment restriction|portfolio|structuring|category|scheme)\b", re.I)),
    ("Fees, Expenses & TER", re.compile(r"\b(fee|expense|ter|commission|charges)\b", re.I)),
    ("Valuation & NAV", re.compile(r"\b(valuation|nav|net asset value|fair value)\b", re.I)),
    ("Settlement & Custody", re.compile(r"\b(settlement|custody|clearing|net settlement)\b", re.I)),
    ("Insider Trading / Fraud / Market Conduct", re.compile(r"\b(insider trading|market abuse|fraud|manipulation|conduct)\b", re.I)),
    ("Cybersecurity & Technology", re.compile(r"\b(cyber|technology|digital|it security|accessibility|garuda|system)\b", re.I)),
    ("Winding-up / Exit / Redemption", re.compile(r"\b(winding.?up|exit|redemption|liquidation|dissolution)\b", re.I)),
    ("Nomination & Investor Protection", re.compile(r"\b(nomination|investor protection|transmission|unclaimed)\b", re.I)),
    ("Enforcement & Penalties", re.compile(r"\b(penalty|enforcement|sanction|fine|prosecution)\b", re.I)),
    ("Cross-border / FPI-specific", re.compile(r"\b(cross.?border|offshore|foreign|fpi|nri|overseas)\b", re.I)),
]


def taxonomy_schema() -> dict:
    return {
        "entities": [SEBI_ENTITY_LABELS[c] for c in SEBI_ENTITY_CODES],
        "entityCodes": SEBI_ENTITY_CODES,
        "entityLabels": SEBI_ENTITY_LABELS,
        "topics": list(SEBI_TOPICS),
        "legalHierarchy": list(HIERARCHY_BY_SECTION.values()),
        "statuses": list(DOCUMENT_STATUSES),
        "relationshipTypes": list(RELATIONSHIP_TYPES),
    }


# Human-readable aliases / keywords for LLM vocabulary (mirrors title regex patterns).
ENTITY_ALIASES: dict[str, list[str]] = {
    "AIF": [
        "AIF", "AIFs", "alternative investment fund", "alternative investment funds",
        "Cat I", "Cat II", "Cat III", "Category I", "Category II", "Category III",
        "AIF Regulations", "AIF Regulations 2012", "SEBI AIF",
    ],
    "Mutual Funds": [
        "mutual fund", "mutual funds", "MF", "AMC", "asset management company",
        "scheme", "NAV", "TER", "MF Regulations", "Mutual Fund Regulations",
        "unit holder", "unitholder", "SIF", "specialized investment fund",
    ],
    "Stock Brokers": [
        "stock broker", "stock brokers", "trading member", "broker", "brokers",
        "derivatives member", "currency derivative", "TM", "trading member",
        "stock broker regulations", "SBTS", "cash segment", "F&O segment",
    ],
    "Portfolio Managers": [
        "portfolio manager", "portfolio managers", "PMS", "PMS Regulations",
        "discretionary PMS", "non-discretionary PMS",
    ],
    "FPIs": [
        "FPI", "FPIs", "foreign portfolio investor", "foreign portfolio investors",
        "foreign institutional investor", "FII", "FIIs", "FPI Regulations",
        "FPI Regulations 2019", "Category I FPI", "Category II FPI",
    ],
    "Custodians": ["custodian", "custodians", "Custodian Regulations", "global custodian"],
    "Merchant Bankers": ["merchant banker", "merchant bankers", "lead manager", "book running lead manager", "BRLM"],
    "RTAs": ["RTA", "RTAs", "registrar", "transfer agent", "registrar and transfer agent", "RTA Regulations"],
    "Debenture Trustees": ["debenture trustee", "debenture trustees", "trustee", "Debenture Trustee Regulations"],
    "Credit Rating Agencies": ["credit rating", "rating agency", "CRA", "credit rating agency", "CRA Regulations"],
    "Underwriters": ["underwriter", "underwriters", "underwriting", "Underwriters Regulations"],
    "Bankers to an Issue": ["banker to an issue", "bankers to an issue", "BTI", "Bankers to an Issue Regulations"],
    "KYC Agencies": ["KRA", "KYC registration agency", "KYC Registration Agency", "KRA Regulations"],
    "Depositories": ["depository", "depositories", "demat", "NSDL", "CDSL", "Depository Regulations", "depository participant", "DP"],
    "Investment Advisers": [
        "investment adviser", "investment advisor", "investment advisers", "RIA",
        "Investment Advisers Regulations", "IA Regulations",
    ],
    "Research Analysts": ["research analyst", "research analysts", "RA Regulations", "Research Analyst Regulations"],
    "Venture Capital": ["venture capital", "VCAT", "VCC", "FVCIs", "foreign venture capital investor", "FVCI Regulations"],
    "General": ["general", "cross-cutting", "all intermediaries", "market wide", "market-wide", "intermediaries"],
}

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "Registration & Licensing": [
        "registration", "license", "licence", "certification", "empanelment",
        "certificate of registration", "COR", "permanent registration", "renewal",
    ],
    "Governance & Fit-and-Proper Criteria": [
        "governance", "fit and proper", "fit-and-proper", "director", "board",
        "compliance officer", "principal officer", "key personnel", "KMP",
    ],
    "Client Onboarding / KYC / Suitability": [
        "KYC", "know your client", "know your customer", "onboarding", "suitability",
        "client due diligence", "CDD", "CKYC", "PAN", "AML", "CFT", "PMLA",
    ],
    "Disclosure & Reporting (periodic, event-based)": [
        "disclosure", "reporting", "periodic", "quarterly", "annual report", "filing",
        "LODR", "listing obligations", "continuous disclosure", "event based", "event-based",
        "shareholding pattern", "financial results", "corporate governance report",
    ],
    "Risk Management & Margins": [
        "risk management", "margin", "margins", "leverage", "exposure", "stress test",
        "peak margin", "SPAN", "VaR", "value at risk", "position limit", "open interest",
    ],
    "Fund Structuring & Investment Restrictions": [
        "investment restriction", "portfolio", "structuring", "category", "scheme",
        "investment objective", "asset allocation", "concentration", "leverage limit",
        "INVIT", "REIT", "infrastructure investment trust", "real estate investment trust",
    ],
    "Fees, Expenses & TER": [
        "fee", "fees", "expense", "expenses", "TER", "total expense ratio",
        "commission", "charges", "brokerage", "expense ratio", "management fee",
    ],
    "Valuation & NAV": [
        "valuation", "NAV", "net asset value", "fair value", "mark to market",
        "MTM", "pricing", "valuation policy", "independent valuer",
    ],
    "Settlement & Custody": [
        "settlement", "custody", "clearing", "net settlement", "T+1", "T+0",
        "clearing corporation", "CC", "collateral", "pledge", "margin pledge",
    ],
    "Insider Trading / Fraud / Market Conduct": [
        "insider trading", "PIT", "prohibition of insider trading", "UPSI",
        "unpublished price sensitive information", "market abuse", "fraud",
        "manipulation", "conduct", "PFUTP", "fraudulent trade", "front running",
    ],
    "Cybersecurity & Technology": [
        "cyber", "cybersecurity", "technology", "digital", "IT security",
        "accessibility", "GARUDA", "system", "SCORES", "SMART ODR", "API",
        "electronic trading", "algorithmic trading", "algo trading",
    ],
    "Winding-up / Exit / Redemption": [
        "winding up", "winding-up", "exit", "redemption", "liquidation", "dissolution",
        "scheme of arrangement", "delisting", "buy-back", "buyback", "open offer",
    ],
    "Nomination & Investor Protection": [
        "nomination", "investor protection", "investor charter", "transmission",
        "unclaimed", "grievance", "SCORES", "ODR", "online dispute resolution",
    ],
    "Enforcement & Penalties": [
        "penalty", "penalties", "enforcement", "sanction", "fine", "prosecution",
        "adjudication", "settlement proceedings", "consent order", "debarment",
    ],
    "Cross-border / FPI-specific": [
        "cross-border", "cross border", "offshore", "foreign", "FPI", "NRI", "overseas",
        "ODI", "FPI limits", "foreign investment", "FPI registration", "FPI KYC",
    ],
}

# Well-known regulation nicknames → entity codes (for LLM resolution).
REGULATION_NICKNAMES: dict[str, dict[str, str]] = {
    "LODR": {"fullName": "SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015", "entities": ["General"], "topics": ["Disclosure & Reporting (periodic, event-based)"]},
    "PIT": {"fullName": "SEBI (Prohibition of Insider Trading) Regulations, 2015", "entities": ["General"], "topics": ["Insider Trading / Fraud / Market Conduct"]},
    "AIF Regulations": {"fullName": "SEBI (Alternative Investment Funds) Regulations, 2012", "entities": ["AIF"], "topics": ["Registration & Licensing"]},
    "FPI Regulations": {"fullName": "SEBI (Foreign Portfolio Investors) Regulations, 2019", "entities": ["FPIs"], "topics": ["Cross-border / FPI-specific"]},
    "ICDR": {"fullName": "SEBI (Issue of Capital and Disclosure Requirements) Regulations, 2018", "entities": ["Merchant Bankers", "Bankers to an Issue"], "topics": ["Disclosure & Reporting (periodic, event-based)"]},
    "SBTS": {"fullName": "SEBI (Stock Brokers and Sub-Brokers) Regulations", "entities": ["Stock Brokers"], "topics": ["Registration & Licensing"]},
    "MF Regulations": {"fullName": "SEBI (Mutual Funds) Regulations, 1996", "entities": ["Mutual Funds"], "topics": ["Fund Structuring & Investment Restrictions"]},
    "PMS Regulations": {"fullName": "SEBI (Portfolio Managers) Regulations, 2020", "entities": ["Portfolio Managers"], "topics": ["Registration & Licensing"]},
    "IA Regulations": {"fullName": "SEBI (Investment Advisers) Regulations, 2013", "entities": ["Investment Advisers"], "topics": ["Registration & Licensing"]},
    "RA Regulations": {"fullName": "SEBI (Research Analysts) Regulations, 2014", "entities": ["Research Analysts"], "topics": ["Registration & Licensing"]},
    "PFUTP": {"fullName": "SEBI (Prohibition of Fraudulent and Unfair Trade Practices) Regulations, 2003", "entities": ["General"], "topics": ["Insider Trading / Fraud / Market Conduct"]},
    "Depository Regulations": {"fullName": "SEBI (Depositories and Participants) Regulations, 2018", "entities": ["Depositories"], "topics": ["Settlement & Custody"]},
    "INVIT Regulations": {"fullName": "SEBI (Infrastructure Investment Trusts) Regulations, 2014", "entities": ["AIF"], "topics": ["Fund Structuring & Investment Restrictions"]},
    "REIT Regulations": {"fullName": "SEBI (Real Estate Investment Trusts) Regulations, 2014", "entities": ["AIF"], "topics": ["Fund Structuring & Investment Restrictions"]},
}

ENTITY_DESCRIPTIONS: dict[str, str] = {
    "Stock Brokers": "Trading members and brokers on stock exchanges (cash, derivatives, currency segments).",
    "Portfolio Managers": "Entities providing discretionary or non-discretionary portfolio management services.",
    "Mutual Funds": "Asset management companies and mutual fund schemes including TER, NAV, and scheme governance.",
    "AIF": "Alternative Investment Funds across Category I, II, and III including VC, PE, and hedge-fund style structures.",
    "Venture Capital": "Venture capital funds and foreign venture capital investors.",
    "FPIs": "Foreign portfolio investors and related cross-border investment routes.",
    "Custodians": "Custodians of securities for FPIs, mutual funds, and other clients.",
    "Merchant Bankers": "Lead managers and issue managers for public and rights issues.",
    "RTAs": "Registrars and transfer agents for mutual funds and listed entities.",
    "Debenture Trustees": "Trustees for debenture and bond issues.",
    "Credit Rating Agencies": "Registered credit rating agencies and their surveillance obligations.",
    "Underwriters": "Underwriters to public issues.",
    "Bankers to an Issue": "Bankers handling issue proceeds and escrow arrangements.",
    "KYC Agencies": "KYC registration agencies under the KRA framework.",
    "Depositories": "NSDL/CDSL and depository participants; demat and settlement infrastructure.",
    "Investment Advisers": "Registered investment advisers and their advisory obligations.",
    "Research Analysts": "Registered research analysts and research report standards.",
    "General": "Cross-cutting rules applying to multiple or all intermediary classes.",
}

TOPIC_DESCRIPTIONS: dict[str, str] = {
    "Registration & Licensing": "Initial and ongoing registration, certification, and empanelment requirements.",
    "Governance & Fit-and-Proper Criteria": "Board composition, fit-and-proper tests, and key personnel standards.",
    "Client Onboarding / KYC / Suitability": "KYC, AML/CFT alignment, suitability, and client due diligence.",
    "Disclosure & Reporting (periodic, event-based)": "Periodic filings, event disclosures, and LODR-style continuous disclosure.",
    "Risk Management & Margins": "Margin collection, leverage limits, risk controls, and stress testing.",
    "Fund Structuring & Investment Restrictions": "Permissible investments, concentration limits, and product structuring.",
    "Fees, Expenses & TER": "Fee caps, expense ratios, and charge disclosure.",
    "Valuation & NAV": "NAV computation, valuation policies, and fair-value standards.",
    "Settlement & Custody": "Clearing, settlement cycles, custody, and collateral.",
    "Insider Trading / Fraud / Market Conduct": "PIT, PFUTP, market abuse, and conduct requirements.",
    "Cybersecurity & Technology": "IT governance, cyber resilience, and platform requirements.",
    "Winding-up / Exit / Redemption": "Scheme closure, delisting, buy-back, and exit routes.",
    "Nomination & Investor Protection": "Nomination, grievance redressal, and investor protection measures.",
    "Enforcement & Penalties": "Penalties, adjudication, and enforcement proceedings.",
    "Cross-border / FPI-specific": "Offshore investor rules, FPI limits, and cross-border flows.",
}

STATUS_SEMANTICS: dict[str, dict[str, str]] = {
    "in_force": {"meaning": "Operative instrument; safe to cite subject to supersession chain check.", "citePolicy": "allow"},
    "superseded": {"meaning": "Replaced by a later instrument.", "citePolicy": "historical_only"},
    "partially_amended": {"meaning": "Still operative but amended in part; read with amendment instruments.", "citePolicy": "allow_with_amendments"},
    "under_consultation": {"meaning": "Draft or consultation paper; not yet operative.", "citePolicy": "draft_only"},
}

ABBREVIATIONS: dict[str, str] = {
    "AIF": "Alternative Investment Fund",
    "AMC": "Asset Management Company",
    "AML": "Anti-Money Laundering",
    "BRLM": "Book Running Lead Manager",
    "BTI": "Banker to an Issue",
    "CC": "Clearing Corporation",
    "CDD": "Client Due Diligence",
    "CDSL": "Central Depository Services Limited",
    "CFD": "Contract for Difference",
    "CFT": "Combating the Financing of Terrorism",
    "CIS": "Collective Investment Scheme",
    "COR": "Certificate of Registration",
    "CRA": "Credit Rating Agency",
    "DP": "Depository Participant",
    "FII": "Foreign Institutional Investor",
    "FPI": "Foreign Portfolio Investor",
    "FVCI": "Foreign Venture Capital Investor",
    "IA": "Investment Adviser",
    "ICDR": "Issue of Capital and Disclosure Requirements",
    "INVIT": "Infrastructure Investment Trust",
    "KMP": "Key Managerial Personnel",
    "KRA": "KYC Registration Agency",
    "KYC": "Know Your Client",
    "LODR": "Listing Obligations and Disclosure Requirements",
    "MF": "Mutual Fund",
    "MTM": "Mark to Market",
    "NAV": "Net Asset Value",
    "NSDL": "National Securities Depository Limited",
    "ODR": "Online Dispute Resolution",
    "PIT": "Prohibition of Insider Trading",
    "PMLA": "Prevention of Money Laundering Act",
    "PFUTP": "Prohibition of Fraudulent and Unfair Trade Practices",
    "PMS": "Portfolio Management Services",
    "RA": "Research Analyst",
    "REIT": "Real Estate Investment Trust",
    "RIA": "Registered Investment Adviser",
    "RTA": "Registrar and Transfer Agent",
    "SBTS": "Stock Brokers and Sub-Brokers",
    "SCORES": "SEBI Complaints Redress System",
    "SEBI": "Securities and Exchange Board of India",
    "TER": "Total Expense Ratio",
    "TM": "Trading Member",
    "UPSI": "Unpublished Price Sensitive Information",
    "VCC": "Venture Capital Company",
}

HIERARCHY_META: list[dict[str, str | int]] = [
    {"id": "act", "label": "Act", "section": "Acts", "rank": 0, "depthTier": "C"},
    {"id": "rule", "label": "Rules", "section": "Rules", "rank": 1, "depthTier": "C"},
    {"id": "regulation", "label": "Regulation", "section": "Regulations", "rank": 2, "depthTier": "C"},
    {"id": "general_order", "label": "General Order", "section": "General Orders", "rank": 3, "depthTier": "B"},
    {"id": "guidance_note", "label": "Guideline", "section": "Guidelines", "rank": 3, "depthTier": "B"},
    {"id": "master_circular", "label": "Master Circular", "section": "Master Circulars", "rank": 4, "depthTier": "C"},
    {"id": "circular", "label": "Circular", "section": "Circulars", "rank": 5, "depthTier": "B"},
    {"id": "gazette_notification", "label": "Gazette Notification", "section": "Gazette Notifications", "rank": 5, "depthTier": "A"},
]

def short_title(title: str, max_len: int = 50) -> str:
    cleaned = re.sub(r"\s+", " ", title.strip())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def document_id_from_url(url: str) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    return f"sebi-{digest}"


def _ordered_unique(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for code in codes:
        if code not in seen and code in SEBI_ENTITY_CODES:
            seen.add(code)
            out.append(code)
    return out


def _entities_from_subject_fragment(fragment: str) -> list[str]:
    hits: list[str] = []
    for pattern, codes in _SUBJECT_ENTITY_RULES:
        if pattern.search(fragment):
            hits.extend(codes)
    return hits


def _entities_from_regulation_references(text: str) -> list[str]:
    hits: list[str] = []
    for match in _REGULATION_IN_TITLE_RE.finditer(text):
        subject = match.group(1)
        hits.extend(_entities_from_subject_fragment(subject))
    return hits


def _entities_from_master_circular_heading(text: str) -> list[str]:
    match = _MASTER_CIRCULAR_FOR_RE.search(text)
    if not match:
        return []
    return _entities_from_subject_fragment(match.group(1))


def infer_entities_from_text(*texts: str | None) -> list[str]:
    """Infer entity codes from one or more text fields (title, summary, official ref)."""
    combined = " ".join(t.strip() for t in texts if t and t.strip())
    if not combined:
        return ["General"]

    hits: list[str] = []
    for code, pattern in _ENTITY_PATTERNS:
        if pattern.search(combined):
            hits.append(code)
    hits.extend(_entities_from_regulation_references(combined))
    hits.extend(_entities_from_master_circular_heading(combined))
    for pattern, codes in _SUBJECT_ENTITY_RULES:
        if pattern.search(combined):
            hits.extend(codes)

    hits = _ordered_unique(hits)
    if not hits:
        return ["General"]
    # Drop General when we have specific intermediary matches.
    if len(hits) > 1 and "General" in hits:
        hits = [h for h in hits if h != "General"]
    return hits[:4]


def infer_entities(title: str) -> list[str]:
    return infer_entities_from_text(title)


def infer_entities_for_document(doc: dict) -> list[str]:
    """Deep entity inference using title, summary, officialId, and section context."""
    title = doc.get("title", "")
    summary = doc.get("summary", "")
    official = doc.get("officialId", "")
    section = doc.get("section", "")
    hits = infer_entities_from_text(title, summary, official)

    # Section-level hints when title is vague (e.g. "To: Stock Exchanges").
    if hits == ["General"] and section == "Master Circulars":
        mc_hits = _entities_from_master_circular_heading(title)
        if mc_hits:
            hits = _ordered_unique(mc_hits)[:4]

    return hits or ["General"]


def retag_catalog_entities(catalog: dict) -> dict:
    """Re-run deep entity tagging across all catalog documents."""
    from datetime import datetime, timezone

    documents = []
    changed = 0
    for doc in catalog.get("documents", []):
        updated = dict(doc)
        new_entities = infer_entities_for_document(updated)
        if new_entities != doc.get("entities"):
            changed += 1
        updated["entities"] = new_entities
        documents.append(updated)
    entities = sorted({code for doc in documents for code in doc.get("entities", [])})
    return {
        **catalog,
        "documents": documents,
        "entities": entities,
        "entitiesRetaggedAt": datetime.now(timezone.utc).isoformat(),
        "entitiesRetagChanged": changed,
    }


def infer_topics(title: str) -> list[str]:
    hits = [topic for topic, pattern in _TOPIC_PATTERNS if pattern.search(title)]
    return hits or ["Disclosure & Reporting (periodic, event-based)"]


def tier_for_hierarchy(hierarchy: LegalHierarchy) -> str:
    if hierarchy in ("act", "regulation", "master_circular"):
        return "C"
    if hierarchy in ("circular", "guidance_note"):
        return "B"
    return "A"


def summarize_from_title(title: str, hierarchy: LegalHierarchy, section: str) -> str:
    """Tier B one-liner derived from metadata — not verbatim SEBI text."""
    entity_hint = ", ".join(infer_entities(title)[:2])
    topic_hint = infer_topics(title)[0]
    return (
        f"SEBI {section} document concerning {topic_hint.lower()} "
        f"({entity_hint}). Metadata-only summary for graph indexing."
    )
