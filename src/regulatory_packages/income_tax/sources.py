"""Canonical incometaxindia.gov.in section sources for corpus crawl."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BASE_URL = "https://www.incometaxindia.gov.in"

FetchMode = Literal["search", "taxonomy", "html"]


@dataclass(frozen=True)
class CatalogSection:
    name: str
    path: str
    hierarchy: str
    fetch_mode: FetchMode = "html"
    search_blueprint: str = ""
    taxonomy_category_id: int | None = None
    partition_by_year: bool = False
    partition_by_act: bool = False
    paginated: bool = True
    max_pages: int = 500
    page_size: int = 50
    description: str = ""


# Liferay taxonomy category IDs (Features vocabulary) + search blueprint ERCs
# discovered from etds-circular-notification / headless-delivery APIs.
CATALOG_SECTIONS: tuple[CatalogSection, ...] = (
    CatalogSection(
        "Provisions (Section-wise)",
        "/income-tax-act",
        "provision",
        fetch_mode="taxonomy",
        taxonomy_category_id=4209131,
        partition_by_year=True,
        page_size=100,
        description="Section-wise Income-tax Act, 1961 provisions (partitioned by year)",
    ),
    CatalogSection(
        "Income-tax Act",
        "/income-tax-act",
        "act",
        fetch_mode="search",
        search_blueprint="ALL_ACTS_BP_ERC",
        page_size=50,
    ),
    CatalogSection(
        "Income-tax Rules",
        "/income-tax-rules",
        "rule",
        fetch_mode="taxonomy",
        taxonomy_category_id=37800,
        partition_by_year=True,
        page_size=50,
    ),
    CatalogSection(
        "Circulars",
        "/circulars",
        "circular",
        fetch_mode="taxonomy",
        taxonomy_category_id=37776,
        page_size=50,
    ),
    CatalogSection(
        "Notifications",
        "/notifications",
        "notification",
        fetch_mode="taxonomy",
        taxonomy_category_id=37788,
        partition_by_year=True,
        page_size=50,
    ),
    CatalogSection(
        "What's New (Press Releases)",
        "/press-release",
        "whats_new",
        fetch_mode="taxonomy",
        taxonomy_category_id=37794,
        partition_by_year=True,
        page_size=50,
        description="Press releases and department updates",
    ),
    CatalogSection(
        "Budget & Finance Bills",
        "/budget-and-bills",
        "finance_act",
        fetch_mode="taxonomy",
        taxonomy_category_id=37767,
        page_size=50,
        description="Budget speeches, finance acts, and bills",
    ),
    CatalogSection(
        "Tax Calendar",
        "/tax-calendar",
        "tax_calendar",
        fetch_mode="search",
        search_blueprint="TAX_CALENDAR_DUE_DATE_BP_ERC",
        page_size=50,
        description="Due dates and filing deadlines",
    ),
    CatalogSection(
        "FAQs",
        "/faqs",
        "faq",
        fetch_mode="taxonomy",
        taxonomy_category_id=4165588,
        page_size=50,
    ),
    CatalogSection(
        "International — DTAA",
        "/international-taxation/dtaa",
        "international",
        fetch_mode="search",
        search_blueprint="DTAA_FULL_TREATY_BP_ERC",
        page_size=50,
    ),
    CatalogSection(
        "International — Transfer Pricing",
        "/international-taxation/transfer-pricing",
        "international",
        fetch_mode="search",
        search_blueprint="DTAA_FULL_TREATY_BP_ERC",
        page_size=50,
        description="Transfer pricing — indexed via DTAA/international corpus",
    ),
    CatalogSection(
        "International — Withholding Tax",
        "/international-taxation/withholding-tax",
        "international",
        fetch_mode="search",
        search_blueprint="DTAA_FULL_TREATY_BP_ERC",
        page_size=50,
    ),
    CatalogSection(
        "International — Non-resident Provisions",
        "/international-taxation/provision-for-non-resident",
        "international",
        fetch_mode="search",
        search_blueprint="ACT_SECTIONS_BP_ERC",
        page_size=50,
        description="Non-resident provisions from Act sections corpus",
    ),
    CatalogSection(
        "International — Advance Rulings",
        "/international-taxation/advance-ruling",
        "international",
        fetch_mode="taxonomy",
        taxonomy_category_id=37788,
        page_size=50,
        description="Advance ruling notifications",
    ),
    CatalogSection(
        "International — Treaty Comparison",
        "/international-taxation/treaty-comparison",
        "international",
        fetch_mode="search",
        search_blueprint="DTAA_FULL_TREATY_BP_ERC",
        page_size=50,
    ),
    CatalogSection(
        "Finance Acts (search index)",
        "/acts/finance-acts",
        "finance_act",
        fetch_mode="search",
        search_blueprint="ALL_ACTS_BP_ERC",
        page_size=50,
    ),
    CatalogSection(
        "Finance Bills",
        "/budget-and-bills/finance-bill",
        "finance_bill",
        fetch_mode="taxonomy",
        taxonomy_category_id=8421685,
        page_size=50,
    ),
)

HIERARCHY_BY_SECTION: dict[str, str] = {s.name: s.hierarchy for s in CATALOG_SECTIONS}
