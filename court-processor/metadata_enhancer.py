#!/usr/bin/env python3
"""
Enhanced Metadata Extractor for Court Documents
===============================================

Extracts judge names and court identifiers from document content and updates both
PostgreSQL metadata and Elasticsearch index with enhanced information.

Addresses GitHub Issues #189 and #190:
- Judge name extraction from multiple sources
- Court identifier extraction and standardization
"""

import os
import sys
import logging
import traceback
import re
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor
from elasticsearch import Elasticsearch

# Import existing extractors
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from extractors.judge import ComprehensiveJudgeExtractor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CourtIdentifierExtractor:
    """Extract and standardize court identifiers from case numbers and content"""

    # Common court identifier patterns in case numbers
    COURT_PATTERNS = {
        # Eastern District of Texas patterns
        r'2:\d+-cv-\d+-JRG': 'txed',
        r'2:\d+-cv-\d+-RSP': 'txed',
        r'2:\d+-cv-\d+-RWS': 'txed',
        r'Case No\. 2:\d+-cv-\d+': 'txed',

        # Delaware District patterns
        r'Civil Action No\. \d+-\d+-CFC': 'ded',
        r'C\.A\. No\. \d+-\d+': 'ded',
        r'Civ\. No\. \d+-\d+-CFC': 'ded',

        # General federal district patterns
        r'\d:\d+-cv-\d+': 'federal_district',
        r'\d:\d+-cr-\d+': 'federal_district',
    }

    # Court name mappings - based on actual document content analysis
    COURT_NAME_MAPPINGS = {
        # Full court names from opinions
        'United States District Court for the Eastern District of Texas': 'txed',
        'United States District Court for the District of Delaware': 'ded',
        'United States District Court for the Southern District of New York': 'nysd',
        'United States District Court for the Northern District of Illinois': 'ilnd',
        'United States District Court for the District of Columbia': 'dcd',
        'Court of International Trade': 'cit',

        # Short forms from docket entries
        'Eastern District of Texas': 'txed',
        'District of Delaware': 'ded',
        'Southern District of New York': 'nysd',
        'Northern District of Illinois': 'ilnd',
        'District of Columbia': 'dcd',

        # Header forms from opinions
        'FOR THE DISTRICT OF DELAWARE': 'ded',
        'FOR THE EASTERN DISTRICT OF TEXAS': 'txed',
        'FOR THE SOUTHERN DISTRICT OF NEW YORK': 'nysd',
        'FOR THE NORTHERN DISTRICT OF ILLINOIS': 'ilnd',
        'FOR THE DISTRICT OF COLUMBIA': 'dcd',

        # Abbreviations
        'E.D. Texas': 'txed',
        'D. Delaware': 'ded',
        'S.D. New York': 'nysd',
        'N.D. Illinois': 'ilnd',
        'D.D.C.': 'dcd',
    }

    @classmethod
    def extract_court_from_case_number(cls, case_number: str) -> Optional[str]:
        """Extract court identifier from case number pattern"""
        if not case_number:
            return None

        for pattern, court_id in cls.COURT_PATTERNS.items():
            if re.search(pattern, case_number, re.IGNORECASE):
                return court_id

        return None

    @classmethod
    def extract_court_from_content(cls, content: str) -> Optional[str]:
        """Extract court identifier from document content"""
        if not content:
            return None

        # Look for court mentions in first 2000 characters
        content_start = content[:2000]

        for court_name, court_id in cls.COURT_NAME_MAPPINGS.items():
            if court_name.lower() in content_start.lower():
                return court_id

        return None

    @classmethod
    def extract_comprehensive_court_info(cls, case_number: str = None,
                                       content: str = None,
                                       existing_metadata: Dict = None) -> Optional[Dict]:
        """Extract court information from all available sources"""

        # Check existing metadata first
        if existing_metadata and existing_metadata.get('court_id'):
            return {
                'court_id': existing_metadata['court_id'],
                'source': 'existing_metadata',
                'confidence': 1.0
            }

        # Try case number pattern first (most reliable)
        if case_number:
            court_from_case = cls.extract_court_from_case_number(case_number)
            if court_from_case and court_from_case != 'federal_district':
                return {
                    'court_id': court_from_case,
                    'source': 'case_number_pattern',
                    'confidence': 0.9
                }

        # Try content extraction
        if content:
            court_from_content = cls.extract_court_from_content(content)
            if court_from_content:
                return {
                    'court_id': court_from_content,
                    'source': 'content_analysis',
                    'confidence': 0.7
                }

        # Fallback to generic federal if we found federal pattern
        if case_number:
            court_from_case = cls.extract_court_from_case_number(case_number)
            if court_from_case == 'federal_district':
                return {
                    'court_id': 'federal_district',
                    'source': 'case_number_generic',
                    'confidence': 0.5
                }

        return None


class JudgeContentExtractor:
    """Extract judge names directly from document content"""

    # Judge name patterns in content - based on actual document analysis
    JUDGE_PATTERNS = [
        # XML author tags in published opinions: <author>RODNEY GILSTRAP, UNITED STATES DISTRICT JUDGE</author>
        r'<author[^>]*>([^<]+?)(?:,\s*UNITED STATES DISTRICT JUDGE|,\s*U\.S\. DISTRICT JUDGE|,\s*DISTRICT JUDGE)[^<]*</author>',

        # Plain text patterns: "WILLIAMS, U.S. District Judge:"
        r'([A-Z][A-Za-z\s\.]+),\s+(?:UNITED STATES DISTRICT JUDGE|U\.S\. DISTRICT JUDGE|DISTRICT JUDGE)',

        # Before patterns: "Before: M. Miller Baker, Judge"
        r'(?:Before:\s+)([A-Z][A-Za-z\s\.]+),\s+Judge',

        # Docket pattern: "Judge: Rodney Gilstrap" (with actual name, not empty)
        r'Judge:\s+([A-Z][A-Za-z\s\.]{5,40})(?:\s*\n|\s*$)',

        # Assigned judge pattern
        r'(?:Assigned Judge:\s+)([A-Z][A-Za-z\s\.]{5,40})(?:\s*\n|\s*$)',
    ]

    @classmethod
    def extract_judge_from_content(cls, content: str) -> Optional[str]:
        """Extract judge name from document content"""
        if not content:
            return None

        # Search in first 3000 characters where judge info is usually located
        content_start = content[:3000]

        for pattern in cls.JUDGE_PATTERNS:
            matches = re.findall(pattern, content_start, re.IGNORECASE)
            if matches:
                judge_name = matches[0].strip()
                # Clean up the judge name
                judge_name = re.sub(r',?\s*(?:UNITED STATES DISTRICT JUDGE|U\.S\. DISTRICT JUDGE|DISTRICT JUDGE).*$', '', judge_name, flags=re.IGNORECASE)
                judge_name = judge_name.strip().rstrip(',.')

                # Validate it's actually a judge name
                invalid_patterns = ['nature of', 'cause:', 'filed:', 'court:', 'docket:', 'case:', 'unassigned', 'assigned']
                if any(invalid.lower() in judge_name.lower() for invalid in invalid_patterns):
                    continue

                # Must contain letters and look like a name (not all numbers or symbols)
                if not re.search(r'[A-Za-z]', judge_name) or len(judge_name.split()) < 2:
                    continue

                if len(judge_name) > 3 and len(judge_name) < 50:  # Reasonable name length
                    return judge_name

        return None


class DocumentDateExtractor:
    """Extract various dates from legal document content"""

    # Date patterns optimized for legal documents - based on actual document analysis
    DATE_PATTERNS = [
        # Filed dates - highest priority as most reliable
        {
            'pattern': r'(?:Filed|FILED):\s*([^\n\r<]+)',
            'type': 'filing_date',
            'confidence': 0.9
        },
        {
            'pattern': r'(?:Date Filed|DATE FILED):\s*([^\n\r<]+)',
            'type': 'filing_date',
            'confidence': 0.9
        },

        # Decision/Entered dates
        {
            'pattern': r'(?:Decided|DECIDED|Entered|ENTERED):\s*([^\n\r<]+)',
            'type': 'decision_date',
            'confidence': 0.9
        },
        {
            'pattern': r'(?:Date Decided|DATE DECIDED|Date Entered|DATE ENTERED):\s*([^\n\r<]+)',
            'type': 'decision_date',
            'confidence': 0.9
        },

        # Order/Opinion dates
        {
            'pattern': r'(?:Order Date|ORDER DATE):\s*([^\n\r<]+)',
            'type': 'document_date',
            'confidence': 0.8
        },

        # In-text dates like "On April 12, 2018"
        {
            'pattern': r'(?:On|on)\s+((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})',
            'type': 'document_date',
            'confidence': 0.7
        },

        # ISO dates (YYYY-MM-DD) - common in metadata
        {
            'pattern': r'(\d{4}-\d{2}-\d{2})',
            'type': 'document_date',
            'confidence': 0.6
        },

        # US format dates (MM/DD/YYYY)
        {
            'pattern': r'(\d{1,2}/\d{1,2}/\d{4})',
            'type': 'document_date',
            'confidence': 0.6
        },

        # Long format dates (Month DD, YYYY)
        {
            'pattern': r'((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})',
            'type': 'document_date',
            'confidence': 0.7
        }
    ]

    @classmethod
    def normalize_date_string(cls, date_str: str) -> Optional[str]:
        """Convert various date formats to ISO 8601 (YYYY-MM-DD)"""
        import re
        from datetime import datetime

        if not date_str or not date_str.strip():
            return None

        date_str = date_str.strip()

        # Clean up common artifacts
        date_str = re.sub(r'<[^>]*>', '', date_str)  # Remove XML tags
        date_str = re.sub(r'\s+', ' ', date_str)     # Normalize whitespace
        date_str = date_str.strip()

        # Try different parsing approaches
        date_formats = [
            '%Y-%m-%d',           # ISO format: 2018-04-12
            '%m/%d/%Y',           # US format: 04/12/2018
            '%B %d, %Y',          # Long format: April 12, 2018
            '%B %d %Y',           # Long format without comma: April 12 2018
            '%b %d, %Y',          # Short month: Apr 12, 2018
            '%b %d %Y',           # Short month without comma: Apr 12 2018
        ]

        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                # Validate reasonable date range for legal documents
                if 1900 <= parsed_date.year <= 2030:
                    return parsed_date.strftime('%Y-%m-%d')
            except ValueError:
                continue

        return None

    @classmethod
    def extract_dates_from_content(cls, content: str) -> List[Dict[str, Any]]:
        """Extract all dates from document content with type and confidence"""
        if not content:
            return []

        # Search in first 3000 characters where dates are typically located
        content_start = content[:3000]
        extracted_dates = []

        for pattern_info in cls.DATE_PATTERNS:
            pattern = pattern_info['pattern']
            date_type = pattern_info['type']
            confidence = pattern_info['confidence']

            matches = re.findall(pattern, content_start, re.IGNORECASE)

            for match in matches:
                # Normalize the date string
                normalized_date = cls.normalize_date_string(match)

                if normalized_date:
                    extracted_dates.append({
                        'date': normalized_date,
                        'type': date_type,
                        'confidence': confidence,
                        'raw_text': match.strip()
                    })

        # Remove duplicates while preserving highest confidence
        unique_dates = {}
        for date_info in extracted_dates:
            key = f"{date_info['date']}_{date_info['type']}"
            if key not in unique_dates or date_info['confidence'] > unique_dates[key]['confidence']:
                unique_dates[key] = date_info

        return list(unique_dates.values())

    @classmethod
    def extract_comprehensive_date_info(cls, content: str = None,
                                      existing_metadata: Dict = None) -> Optional[Dict]:
        """Extract comprehensive date information from all sources"""

        # Check existing metadata first
        if existing_metadata:
            has_filing_date = existing_metadata.get('filing_date')
            has_decision_date = existing_metadata.get('decision_date')
            has_document_date = existing_metadata.get('document_date')

            if has_filing_date and has_decision_date and has_document_date:
                return {
                    'dates_found': True,
                    'source': 'existing_metadata',
                    'confidence': 1.0
                }

        # Extract from content
        if content:
            extracted_dates = cls.extract_dates_from_content(content)

            if extracted_dates:
                # Organize by type
                date_info = {
                    'filing_date': None,
                    'decision_date': None,
                    'document_date': None,
                    'all_dates': extracted_dates
                }

                # Get the highest confidence date for each type
                for date_obj in extracted_dates:
                    date_type = date_obj['type']
                    if not date_info[date_type] or date_obj['confidence'] > date_info[date_type]['confidence']:
                        date_info[date_type] = date_obj

                # Return the structured information
                return {
                    'dates_found': True,
                    'source': 'content_extraction',
                    'confidence': max(d['confidence'] for d in extracted_dates),
                    'extracted_info': date_info
                }

        return None


class LegalCitationExtractor:
    """Extract legal citations and references from document content"""

    # Citation patterns for different legal reference types
    CITATION_PATTERNS = [
        # U.S. Code citations: 42 U.S.C. § 1983, 28 USC 1400
        {
            'pattern': r'(\d+\s+U\.?S\.?C\.?\s*§?\s*\d+(?:\([^)]+\))?)',
            'type': 'usc',
            'confidence': 0.9
        },

        # Federal Register citations: Fed. R. Civ. P. 12(b)(6)
        {
            'pattern': r'(Fed\.?\s*R\.?\s*(?:Civ\.?\s*P\.?|Crim\.?\s*P\.?|App\.?\s*P\.?|Evid\.?)\s*\d+[a-z]?(?:\([^)]+\))?)',
            'type': 'federal_rules',
            'confidence': 0.9
        },

        # Federal Reporter citations: 871 F.3d 1355, 536 F.2d 123
        {
            'pattern': r'(\d+\s+F\.?\d*d?\s+\d+)',
            'type': 'federal_reporter',
            'confidence': 0.8
        },

        # U.S. Supreme Court citations: 536 U.S. 304
        {
            'pattern': r'(\d+\s+U\.S\.?\s+\d+)',
            'type': 'supreme_court',
            'confidence': 0.9
        },

        # Code of Federal Regulations: 29 C.F.R. § 825.100
        {
            'pattern': r'(\d+\s+C\.F\.R\.?\s*§?\s*\d+(?:\.\d+)*)',
            'type': 'cfr',
            'confidence': 0.8
        }
    ]

    @classmethod
    def extract_citations_from_content(cls, content: str) -> List[Dict[str, Any]]:
        """Extract all legal citations from document content"""
        if not content:
            return []

        # Search in first 10000 characters where citations are most relevant
        content_search = content[:10000]
        extracted_citations = []

        for pattern_info in cls.CITATION_PATTERNS:
            pattern = pattern_info['pattern']
            citation_type = pattern_info['type']
            confidence = pattern_info['confidence']

            matches = re.findall(pattern, content_search, re.IGNORECASE)

            for match in matches:
                # Clean up the citation
                clean_citation = re.sub(r'\s+', ' ', match).strip()

                extracted_citations.append({
                    'citation': clean_citation,
                    'type': citation_type,
                    'confidence': confidence
                })

        # Remove duplicates while preserving highest confidence
        unique_citations = {}
        for citation_info in extracted_citations:
            key = f"{citation_info['citation']}_{citation_info['type']}"
            if key not in unique_citations or citation_info['confidence'] > unique_citations[key]['confidence']:
                unique_citations[key] = citation_info

        return list(unique_citations.values())

    @classmethod
    def extract_comprehensive_citation_info(cls, content: str = None,
                                          existing_metadata: Dict = None) -> Optional[Dict]:
        """Extract comprehensive citation information"""

        # Check existing metadata first
        if existing_metadata and existing_metadata.get('legal_citations'):
            return {
                'citations_found': True,
                'source': 'existing_metadata',
                'confidence': 1.0
            }

        # Extract from content
        if content:
            extracted_citations = cls.extract_citations_from_content(content)

            if extracted_citations:
                # Organize by type
                citation_info = {
                    'usc_citations': [c for c in extracted_citations if c['type'] == 'usc'],
                    'federal_rules': [c for c in extracted_citations if c['type'] == 'federal_rules'],
                    'case_citations': [c for c in extracted_citations if c['type'] in ['federal_reporter', 'supreme_court']],
                    'cfr_citations': [c for c in extracted_citations if c['type'] == 'cfr'],
                    'all_citations': extracted_citations
                }

                return {
                    'citations_found': True,
                    'source': 'content_extraction',
                    'confidence': max(c['confidence'] for c in extracted_citations),
                    'extracted_info': citation_info
                }

        return None


class CaseDispositionExtractor:
    """Extract case dispositions and rulings from document content"""

    # Disposition patterns for different types of rulings
    DISPOSITION_PATTERNS = [
        # Motion dispositions
        {
            'pattern': r'\b(GRANTED|DENIED|DISMISSED)\b',
            'type': 'motion_disposition',
            'confidence': 0.9
        },

        # Appeal dispositions
        {
            'pattern': r'\b(AFFIRMED|REVERSED|VACATED|REMANDED)\b',
            'type': 'appeal_disposition',
            'confidence': 0.9
        },

        # Case closures
        {
            'pattern': r'\b(CLOSED|TERMINATED|STAYED)\b',
            'type': 'case_status',
            'confidence': 0.8
        },

        # Injunction types
        {
            'pattern': r'\b(ENJOINED|RESTRAINED|PRELIMINARY INJUNCTION|PERMANENT INJUNCTION)\b',
            'type': 'injunction',
            'confidence': 0.8
        }
    ]

    @classmethod
    def extract_dispositions_from_content(cls, content: str) -> List[Dict[str, Any]]:
        """Extract all case dispositions from document content"""
        if not content:
            return []

        # Search in first 5000 characters where dispositions are typically announced
        content_search = content[:5000]
        extracted_dispositions = []

        for pattern_info in cls.DISPOSITION_PATTERNS:
            pattern = pattern_info['pattern']
            disposition_type = pattern_info['type']
            confidence = pattern_info['confidence']

            matches = re.findall(pattern, content_search, re.IGNORECASE)

            for match in matches:
                disposition = match.upper().strip()

                extracted_dispositions.append({
                    'disposition': disposition,
                    'type': disposition_type,
                    'confidence': confidence
                })

        # Remove duplicates while preserving highest confidence
        unique_dispositions = {}
        for disp_info in extracted_dispositions:
            key = f"{disp_info['disposition']}_{disp_info['type']}"
            if key not in unique_dispositions or disp_info['confidence'] > unique_dispositions[key]['confidence']:
                unique_dispositions[key] = disp_info

        return list(unique_dispositions.values())

    @classmethod
    def extract_comprehensive_disposition_info(cls, content: str = None,
                                             existing_metadata: Dict = None) -> Optional[Dict]:
        """Extract comprehensive disposition information"""

        # Check existing metadata first
        if existing_metadata and existing_metadata.get('case_dispositions'):
            return {
                'dispositions_found': True,
                'source': 'existing_metadata',
                'confidence': 1.0
            }

        # Extract from content
        if content:
            extracted_dispositions = cls.extract_dispositions_from_content(content)

            if extracted_dispositions:
                # Organize by type
                disposition_info = {
                    'motion_rulings': [d for d in extracted_dispositions if d['type'] == 'motion_disposition'],
                    'appeal_outcomes': [d for d in extracted_dispositions if d['type'] == 'appeal_disposition'],
                    'case_status': [d for d in extracted_dispositions if d['type'] == 'case_status'],
                    'injunctions': [d for d in extracted_dispositions if d['type'] == 'injunction'],
                    'all_dispositions': extracted_dispositions
                }

                return {
                    'dispositions_found': True,
                    'source': 'content_extraction',
                    'confidence': max(d['confidence'] for d in extracted_dispositions),
                    'extracted_info': disposition_info
                }

        return None


class LegalTopicClassifier:
    """Extract and classify legal topics from document content"""

    # Legal topic classification patterns
    TOPIC_PATTERNS = [
        # Constitutional Law
        {
            'keywords': ['constitutional', 'first amendment', 'fourth amendment', 'fifth amendment',
                        'fourteenth amendment', 'due process', 'equal protection', 'bill of rights',
                        'constitutional challenge', 'constitutional violation'],
            'topic': 'Constitutional Law',
            'confidence': 0.9
        },

        # Contract Law
        {
            'keywords': ['contract', 'breach of contract', 'contractual obligation', 'agreement',
                        'warranty', 'breach of warranty', 'consideration', 'offer and acceptance',
                        'contractual dispute', 'breach of agreement'],
            'topic': 'Contract Law',
            'confidence': 0.8
        },

        # Intellectual Property
        {
            'keywords': ['patent', 'copyright', 'trademark', 'trade secret', 'infringement',
                        'patent infringement', 'copyright infringement', 'trademark infringement',
                        'intellectual property', 'DMCA', 'fair use'],
            'topic': 'Intellectual Property',
            'confidence': 0.9
        },

        # Criminal Procedure
        {
            'keywords': ['criminal procedure', 'search and seizure', 'miranda rights', 'arrest',
                        'probable cause', 'warrant', 'suppression', 'exclusionary rule',
                        'criminal defendant', 'prosecution'],
            'topic': 'Criminal Procedure',
            'confidence': 0.8
        },

        # Employment Law
        {
            'keywords': ['employment', 'discrimination', 'wrongful termination', 'harassment',
                        'Title VII', 'ADA', 'FMLA', 'wage and hour', 'overtime',
                        'employment contract', 'workplace'],
            'topic': 'Employment Law',
            'confidence': 0.8
        },

        # Civil Rights
        {
            'keywords': ['civil rights', 'section 1983', '42 U.S.C. § 1983', 'qualified immunity',
                        'civil rights violation', 'discrimination', 'equal protection',
                        'civil liberties', 'constitutional rights'],
            'topic': 'Civil Rights',
            'confidence': 0.9
        },

        # Tax Law
        {
            'keywords': ['tax', 'taxation', 'IRS', 'Internal Revenue Service', 'tax liability',
                        'tax evasion', 'tax code', 'deduction', 'exemption', 'tax return'],
            'topic': 'Tax Law',
            'confidence': 0.8
        },

        # Securities Law
        {
            'keywords': ['securities', 'SEC', 'Securities and Exchange Commission', 'fraud',
                        'securities fraud', 'insider trading', 'disclosure', 'registration',
                        'investment', 'stock'],
            'topic': 'Securities Law',
            'confidence': 0.9
        },

        # Immigration Law
        {
            'keywords': ['immigration', 'deportation', 'asylum', 'visa', 'green card',
                        'naturalization', 'ICE', 'immigration court', 'removal proceedings',
                        'immigration status'],
            'topic': 'Immigration Law',
            'confidence': 0.8
        },

        # Environmental Law
        {
            'keywords': ['environmental', 'EPA', 'Clean Air Act', 'Clean Water Act', 'CERCLA',
                        'environmental protection', 'pollution', 'contamination', 'NEPA',
                        'environmental impact'],
            'topic': 'Environmental Law',
            'confidence': 0.8
        },

        # Antitrust Law
        {
            'keywords': ['antitrust', 'monopoly', 'competition', 'Sherman Act', 'Clayton Act',
                        'price fixing', 'market manipulation', 'restraint of trade',
                        'competitive harm', 'market power'],
            'topic': 'Antitrust Law',
            'confidence': 0.9
        },

        # Corporate Law
        {
            'keywords': ['corporate', 'corporation', 'shareholder', 'board of directors',
                        'fiduciary duty', 'merger', 'acquisition', 'corporate governance',
                        'business judgment rule', 'derivative suit'],
            'topic': 'Corporate Law',
            'confidence': 0.8
        },

        # Bankruptcy Law
        {
            'keywords': ['bankruptcy', 'Chapter 7', 'Chapter 11', 'Chapter 13', 'debtor',
                        'creditor', 'discharge', 'liquidation', 'reorganization',
                        'automatic stay'],
            'topic': 'Bankruptcy Law',
            'confidence': 0.9
        },

        # Administrative Law
        {
            'keywords': ['administrative law', 'agency action', 'rulemaking', 'APA',
                        'Administrative Procedure Act', 'judicial review', 'arbitrary and capricious',
                        'substantial evidence', 'agency decision'],
            'topic': 'Administrative Law',
            'confidence': 0.8
        },

        # Evidence Law
        {
            'keywords': ['evidence', 'Federal Rules of Evidence', 'hearsay', 'privilege',
                        'authentication', 'best evidence rule', 'expert testimony',
                        'admissibility', 'relevance'],
            'topic': 'Evidence Law',
            'confidence': 0.8
        }
    ]

    @classmethod
    def _is_metadata_only_content(cls, content: str) -> bool:
        """Check if content is metadata-only and should be skipped for topic classification"""
        if not content:
            return True

        # Skip JSON/dict API metadata from CourtListener (all formats)
        content_clean = content.strip()
        if (content_clean.startswith('{"resource_uri":') or
            content_clean.startswith("{'resource_uri':") or
            content_clean.startswith('{\n  "resource_uri":') or
            content_clean.startswith("{\n  'resource_uri':")):
            return True

        # Additional check for JSON structure with resource_uri field
        if (content_clean.startswith('{') and
            '"resource_uri"' in content[:200] and
            '"courtlistener.com"' in content[:500]):
            return True

        # Skip very short case summaries (but allow substantial ones)
        if content.startswith('Case:') and len(content) < 500:
            return True

        # For other content, require minimum length for meaningful classification
        if len(content) < 500:
            return True

        # Check for legal document indicators - if present, don't filter
        legal_indicators = [
            '<opinion', '<author', 'JUDGE', 'DISTRICT JUDGE', 'MAGISTRATE JUDGE',
            'Federal Rule', 'U.S.C.', 'motion to dismiss', 'summary judgment',
            'GRANTED', 'DENIED', 'ORDERED', 'IT IS HEREBY', 'Before the Court'
        ]

        content_upper = content.upper()
        for indicator in legal_indicators:
            if indicator.upper() in content_upper:
                return False  # Don't filter legal documents

        # For remaining content, check text density
        # Skip if mostly structured data with little prose
        lines = content.split('\n')
        substantial_lines = [line for line in lines
                           if len(line.strip()) > 30
                           and not line.strip().startswith(('{', '"', '['))]

        # Require at least 3 substantial prose lines for classification
        return len(substantial_lines) < 3

    @classmethod
    def extract_topics_from_content(cls, content: str) -> List[Dict[str, Any]]:
        """Extract legal topics from document content"""
        if not content:
            return []

        # Quality control: Skip metadata-only documents
        if cls._is_metadata_only_content(content):
            return []

        # Convert to lowercase for case-insensitive matching
        content_lower = content.lower()
        extracted_topics = []

        for topic_info in cls.TOPIC_PATTERNS:
            keywords = topic_info['keywords']
            topic = topic_info['topic']
            base_confidence = topic_info['confidence']

            # Count keyword matches
            keyword_matches = []
            for keyword in keywords:
                if keyword.lower() in content_lower:
                    keyword_matches.append(keyword)

            # Require at least 2 keyword matches for topic assignment
            if len(keyword_matches) >= 2:
                # Adjust confidence based on number of matches
                confidence = min(base_confidence + (len(keyword_matches) - 2) * 0.05, 0.95)

                extracted_topics.append({
                    'topic': topic,
                    'confidence': confidence,
                    'matched_keywords': keyword_matches[:5]  # Limit to top 5 matches
                })

        # Sort by confidence and remove duplicates
        extracted_topics.sort(key=lambda x: x['confidence'], reverse=True)

        # Return top 3 most confident topics
        return extracted_topics[:3]

    @classmethod
    def extract_comprehensive_topic_info(cls, content: str = None,
                                       existing_metadata: Dict = None) -> Optional[Dict]:
        """Extract comprehensive legal topic information"""

        # Check existing metadata first
        if existing_metadata and existing_metadata.get('legal_topics'):
            return {
                'topics_found': True,
                'source': 'existing_metadata',
                'confidence': 1.0,
                'topic_count': len(existing_metadata['legal_topics'])
            }

        # Extract from content
        if content:
            extracted_topics = cls.extract_topics_from_content(content)

            if extracted_topics:
                # Organize topics by confidence level
                high_confidence = [t for t in extracted_topics if t['confidence'] >= 0.85]
                medium_confidence = [t for t in extracted_topics if 0.7 <= t['confidence'] < 0.85]
                low_confidence = [t for t in extracted_topics if t['confidence'] < 0.7]

                topic_info = {
                    'all_topics': extracted_topics,
                    'primary_topics': high_confidence,
                    'secondary_topics': medium_confidence,
                    'potential_topics': low_confidence
                }

                return {
                    'topics_found': True,
                    'source': 'content_extraction',
                    'confidence': max(t['confidence'] for t in extracted_topics),
                    'extracted_info': topic_info
                }

        return None


class MetadataEnhancer:
    """Main service for enhancing document metadata"""

    def __init__(self):
        """Initialize the enhancer with database and Elasticsearch connections"""

        # Configuration from environment
        self.db_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', '8200')),  # Use the external port
            'database': os.getenv('DB_NAME', 'aletheia'),
            'user': os.getenv('DB_USER', 'aletheia'),
            'password': os.getenv('DB_PASSWORD', 'DzpmbGc2FoLDlHLnuz_nGZkmjW0G1Ofq')
        }

        self.es_host = os.getenv('ELASTICSEARCH_HOST', 'http://localhost:9200')
        self.es_index = os.getenv('ELASTICSEARCH_INDEX', 'court-documents')

        # Initialize connections
        self.db_conn = None
        self.es_client = None

        # Enhancement statistics
        self.stats = {
            'documents_processed': 0,
            'judges_extracted': 0,
            'courts_extracted': 0,
            'dates_extracted': 0,
            'citations_extracted': 0,
            'dispositions_extracted': 0,
            'topics_extracted': 0,
            'metadata_updates': 0,
            'elasticsearch_updates': 0,
            'errors': []
        }

    def connect(self) -> bool:
        """Establish connections to PostgreSQL and Elasticsearch"""
        try:
            # Connect to PostgreSQL
            logger.info(f"Connecting to PostgreSQL at {self.db_config['host']}:{self.db_config['port']}")
            self.db_conn = psycopg2.connect(**self.db_config)
            logger.info("✅ PostgreSQL connection established")

            # Connect to Elasticsearch
            logger.info(f"Connecting to Elasticsearch at {self.es_host}")
            self.es_client = Elasticsearch([self.es_host])

            # Test Elasticsearch connection
            if not self.es_client.ping():
                raise Exception("Elasticsearch ping failed")
            logger.info("✅ Elasticsearch connection established")

            return True

        except Exception as e:
            logger.error(f"❌ Connection failed: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def get_documents_needing_enhancement(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get documents that need judge or court metadata enhancement"""
        try:
            cursor = self.db_conn.cursor(cursor_factory=RealDictCursor)

            # Find documents missing judge or court information
            query = """
                SELECT id, case_number, case_name, document_type, content, metadata
                FROM court_documents
                WHERE content IS NOT NULL AND content != ''
                AND content NOT ILIKE '%paid tier access%'
                AND (
                    metadata IS NULL
                    OR metadata->>'judge_name' IS NULL
                    OR metadata->>'court_id' IS NULL
                    OR NOT (metadata::jsonb ? 'legal_citations')
                    OR NOT (metadata::jsonb ? 'case_dispositions')
                )
                ORDER BY id
            """

            if limit:
                query += f" LIMIT {limit}"

            cursor.execute(query)
            documents = cursor.fetchall()

            logger.info(f"Found {len(documents)} documents needing enhancement")
            cursor.close()

            return [dict(doc) for doc in documents]

        except Exception as e:
            logger.error(f"❌ Failed to fetch documents: {str(e)}")
            return []

    def enhance_document_metadata(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and enhance metadata for a single document"""
        try:
            doc_id = doc['id']
            case_number = doc.get('case_number')
            content = doc.get('content', '')
            existing_metadata = doc.get('metadata', {})

            if isinstance(existing_metadata, str):
                try:
                    existing_metadata = json.loads(existing_metadata)
                except:
                    existing_metadata = {}

            enhanced_metadata = existing_metadata.copy()
            extraction_sources = {}

            # Extract judge information if missing
            if not enhanced_metadata.get('judge_name'):
                # Try existing comprehensive extractor first (for docket/API data)
                judge_info = ComprehensiveJudgeExtractor.extract_comprehensive_judge_info(
                    docket_number=case_number
                )

                if judge_info:
                    enhanced_metadata['judge_name'] = judge_info.name
                    extraction_sources['judge_source'] = judge_info.source
                    extraction_sources['judge_confidence'] = judge_info.confidence
                    self.stats['judges_extracted'] += 1
                else:
                    # Try content-based extraction
                    judge_from_content = JudgeContentExtractor.extract_judge_from_content(content)
                    if judge_from_content:
                        enhanced_metadata['judge_name'] = judge_from_content
                        extraction_sources['judge_source'] = 'content_extraction'
                        extraction_sources['judge_confidence'] = 0.8
                        self.stats['judges_extracted'] += 1

            # Extract court information if missing
            if not enhanced_metadata.get('court_id'):
                court_info = CourtIdentifierExtractor.extract_comprehensive_court_info(
                    case_number=case_number,
                    content=content,
                    existing_metadata=existing_metadata
                )

                if court_info:
                    enhanced_metadata['court_id'] = court_info['court_id']
                    extraction_sources['court_source'] = court_info['source']
                    extraction_sources['court_confidence'] = court_info['confidence']
                    self.stats['courts_extracted'] += 1

            # Extract date information if missing
            missing_dates = (
                not enhanced_metadata.get('filing_date') or
                not enhanced_metadata.get('decision_date') or
                not enhanced_metadata.get('document_date')
            )

            if missing_dates:
                date_info = DocumentDateExtractor.extract_comprehensive_date_info(
                    content=content,
                    existing_metadata=enhanced_metadata
                )

                if date_info and date_info.get('dates_found'):
                    if date_info['source'] == 'content_extraction':
                        extracted_info = date_info['extracted_info']

                        # Add filing date if found and missing
                        if extracted_info.get('filing_date') and not enhanced_metadata.get('filing_date'):
                            enhanced_metadata['filing_date'] = extracted_info['filing_date']['date']
                            extraction_sources['filing_date_source'] = 'content_extraction'
                            extraction_sources['filing_date_confidence'] = extracted_info['filing_date']['confidence']

                        # Add decision date if found and missing
                        if extracted_info.get('decision_date') and not enhanced_metadata.get('decision_date'):
                            enhanced_metadata['decision_date'] = extracted_info['decision_date']['date']
                            extraction_sources['decision_date_source'] = 'content_extraction'
                            extraction_sources['decision_date_confidence'] = extracted_info['decision_date']['confidence']

                        # Add document date if found and missing
                        if extracted_info.get('document_date') and not enhanced_metadata.get('document_date'):
                            enhanced_metadata['document_date'] = extracted_info['document_date']['date']
                            extraction_sources['document_date_source'] = 'content_extraction'
                            extraction_sources['document_date_confidence'] = extracted_info['document_date']['confidence']

                        # Store all extracted dates for reference
                        if extracted_info.get('all_dates'):
                            enhanced_metadata['extracted_dates'] = extracted_info['all_dates']

                        # Update stats
                        if not hasattr(self.stats, 'dates_extracted'):
                            self.stats['dates_extracted'] = 0
                        self.stats['dates_extracted'] += len(extracted_info.get('all_dates', []))

            # Extract legal citations if missing
            if not enhanced_metadata.get('legal_citations'):
                citation_info = LegalCitationExtractor.extract_comprehensive_citation_info(
                    content=content,
                    existing_metadata=enhanced_metadata
                )

                if citation_info and citation_info.get('citations_found'):
                    if citation_info['source'] == 'content_extraction':
                        extracted_info = citation_info['extracted_info']
                        enhanced_metadata['legal_citations'] = extracted_info['all_citations']

                        # Store organized citation types
                        if extracted_info.get('usc_citations'):
                            enhanced_metadata['usc_citations'] = extracted_info['usc_citations']
                        if extracted_info.get('federal_rules'):
                            enhanced_metadata['federal_rules'] = extracted_info['federal_rules']
                        if extracted_info.get('case_citations'):
                            enhanced_metadata['case_citations'] = extracted_info['case_citations']
                        if extracted_info.get('cfr_citations'):
                            enhanced_metadata['cfr_citations'] = extracted_info['cfr_citations']

                        extraction_sources['citations_source'] = 'content_extraction'
                        extraction_sources['citations_confidence'] = citation_info['confidence']

                        # Update stats
                        if not hasattr(self.stats, 'citations_extracted'):
                            self.stats['citations_extracted'] = 0
                        self.stats['citations_extracted'] += len(extracted_info.get('all_citations', []))

            # Extract case dispositions if missing
            if not enhanced_metadata.get('case_dispositions'):
                disposition_info = CaseDispositionExtractor.extract_comprehensive_disposition_info(
                    content=content,
                    existing_metadata=enhanced_metadata
                )

                if disposition_info and disposition_info.get('dispositions_found'):
                    if disposition_info['source'] == 'content_extraction':
                        extracted_info = disposition_info['extracted_info']
                        enhanced_metadata['case_dispositions'] = extracted_info['all_dispositions']

                        # Store organized disposition types
                        if extracted_info.get('motion_rulings'):
                            enhanced_metadata['motion_rulings'] = extracted_info['motion_rulings']
                        if extracted_info.get('appeal_outcomes'):
                            enhanced_metadata['appeal_outcomes'] = extracted_info['appeal_outcomes']
                        if extracted_info.get('case_status'):
                            enhanced_metadata['case_status'] = extracted_info['case_status']

                        extraction_sources['dispositions_source'] = 'content_extraction'
                        extraction_sources['dispositions_confidence'] = disposition_info['confidence']

                        # Update stats
                        if not hasattr(self.stats, 'dispositions_extracted'):
                            self.stats['dispositions_extracted'] = 0
                        self.stats['dispositions_extracted'] += len(extracted_info.get('all_dispositions', []))

            # Extract legal topics if missing
            if not enhanced_metadata.get('legal_topics'):
                topic_info = LegalTopicClassifier.extract_comprehensive_topic_info(
                    content=content,
                    existing_metadata=enhanced_metadata
                )

                if topic_info and topic_info.get('topics_found'):
                    if topic_info['source'] == 'content_extraction':
                        extracted_info = topic_info['extracted_info']
                        enhanced_metadata['legal_topics'] = extracted_info['all_topics']

                        # Store organized topic categories
                        if extracted_info.get('primary_topics'):
                            enhanced_metadata['primary_topics'] = extracted_info['primary_topics']
                        if extracted_info.get('secondary_topics'):
                            enhanced_metadata['secondary_topics'] = extracted_info['secondary_topics']
                        if extracted_info.get('potential_topics'):
                            enhanced_metadata['potential_topics'] = extracted_info['potential_topics']

                        extraction_sources['topics_source'] = 'content_extraction'
                        extraction_sources['topics_confidence'] = topic_info['confidence']

                        # Update stats
                        if not hasattr(self.stats, 'topics_extracted'):
                            self.stats['topics_extracted'] = 0
                        self.stats['topics_extracted'] += len(extracted_info.get('all_topics', []))

            # Add extraction metadata
            if extraction_sources:
                enhanced_metadata['enhancement_info'] = {
                    'enhanced_at': datetime.now(timezone.utc).isoformat(),
                    'sources': extraction_sources
                }

            return enhanced_metadata

        except Exception as e:
            logger.error(f"❌ Failed to enhance document {doc.get('id')}: {str(e)}")
            self.stats['errors'].append(f"Document {doc.get('id')}: {str(e)}")
            return existing_metadata

    def update_database_metadata(self, doc_id: int, enhanced_metadata: Dict[str, Any]) -> bool:
        """Update document metadata in PostgreSQL"""
        try:
            cursor = self.db_conn.cursor()

            update_query = """
                UPDATE court_documents
                SET metadata = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """

            cursor.execute(update_query, (json.dumps(enhanced_metadata), doc_id))
            self.db_conn.commit()
            cursor.close()

            self.stats['metadata_updates'] += 1
            return True

        except Exception as e:
            logger.error(f"❌ Failed to update database for document {doc_id}: {str(e)}")
            return False

    def update_elasticsearch_document(self, doc_id: int, enhanced_metadata: Dict[str, Any]) -> bool:
        """Update document in Elasticsearch with enhanced metadata"""
        try:
            if not self.es_client.exists(index=self.es_index, id=doc_id):
                logger.warning(f"Document {doc_id} not found in Elasticsearch")
                return False

            # Update with new metadata fields
            update_body = {
                'doc': {
                    'judge_name': enhanced_metadata.get('judge_name'),
                    'court_id': enhanced_metadata.get('court_id'),
                    'filing_date': enhanced_metadata.get('filing_date'),
                    'decision_date': enhanced_metadata.get('decision_date'),
                    'document_date': enhanced_metadata.get('document_date'),
                    'enhanced_at': datetime.now(timezone.utc)
                }
            }

            # Remove None values
            update_body['doc'] = {k: v for k, v in update_body['doc'].items() if v is not None}

            self.es_client.update(
                index=self.es_index,
                id=doc_id,
                body=update_body
            )

            self.stats['elasticsearch_updates'] += 1
            return True

        except Exception as e:
            logger.error(f"❌ Failed to update Elasticsearch for document {doc_id}: {str(e)}")
            return False

    def enhance_all_documents(self, batch_size: int = 50, limit: Optional[int] = None) -> bool:
        """Enhance metadata for all documents needing enhancement"""
        try:
            logger.info("🚀 Starting metadata enhancement")

            # Reset stats
            self.stats = {
                'documents_processed': 0,
                'judges_extracted': 0,
                'courts_extracted': 0,
                'dates_extracted': 0,
                'citations_extracted': 0,
                'dispositions_extracted': 0,
                'metadata_updates': 0,
                'elasticsearch_updates': 0,
                'errors': []
            }

            # Get documents needing enhancement
            documents = self.get_documents_needing_enhancement(limit=limit)

            if not documents:
                logger.info("✅ No documents need enhancement")
                return True

            logger.info(f"📄 Processing {len(documents)} documents")

            for i, doc in enumerate(documents):
                doc_id = doc['id']

                try:
                    # Enhance metadata
                    enhanced_metadata = self.enhance_document_metadata(doc)

                    # Update database
                    db_success = self.update_database_metadata(doc_id, enhanced_metadata)

                    # Update Elasticsearch if document exists there
                    es_success = self.update_elasticsearch_document(doc_id, enhanced_metadata)

                    self.stats['documents_processed'] += 1

                    if (i + 1) % 10 == 0:
                        logger.info(f"Processed {i + 1}/{len(documents)} documents...")

                except Exception as e:
                    logger.error(f"❌ Failed to process document {doc_id}: {str(e)}")
                    self.stats['errors'].append(f"Document {doc_id}: {str(e)}")

            self.print_enhancement_summary()
            return len(self.stats['errors']) == 0

        except Exception as e:
            logger.error(f"❌ Enhancement failed: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    def print_enhancement_summary(self):
        """Print a summary of the enhancement operation"""
        logger.info("\n" + "="*60)
        logger.info("METADATA ENHANCEMENT SUMMARY")
        logger.info("="*60)
        logger.info(f"Documents processed: {self.stats['documents_processed']}")
        logger.info(f"Judges extracted: {self.stats['judges_extracted']}")
        logger.info(f"Courts extracted: {self.stats['courts_extracted']}")
        logger.info(f"Dates extracted: {self.stats['dates_extracted']}")
        logger.info(f"Citations extracted: {self.stats['citations_extracted']}")
        logger.info(f"Dispositions extracted: {self.stats['dispositions_extracted']}")
        logger.info(f"Topics extracted: {self.stats['topics_extracted']}")
        logger.info(f"Database updates: {self.stats['metadata_updates']}")
        logger.info(f"Elasticsearch updates: {self.stats['elasticsearch_updates']}")

        if self.stats['errors']:
            logger.error(f"Errors encountered: {len(self.stats['errors'])}")
            for error in self.stats['errors'][:5]:  # Show first 5 errors
                logger.error(f"  - {error}")
            if len(self.stats['errors']) > 5:
                logger.error(f"  ... and {len(self.stats['errors']) - 5} more errors")

        logger.info("="*60)

    def close(self):
        """Close all connections"""
        try:
            if self.db_conn:
                self.db_conn.close()
                logger.info("PostgreSQL connection closed")

            if self.es_client:
                logger.info("Elasticsearch client closed")

        except Exception as e:
            logger.error(f"Error closing connections: {str(e)}")


def main():
    """Main entry point for the metadata enhancer"""
    import argparse

    parser = argparse.ArgumentParser(description='Enhance document metadata with judge and court information')
    parser.add_argument('--enhance-all', action='store_true',
                       help='Enhance all documents missing metadata')
    parser.add_argument('--batch-size', type=int, default=50,
                       help='Batch size for processing (default: 50)')
    parser.add_argument('--limit', type=int,
                       help='Limit number of documents to process (for testing)')
    parser.add_argument('--test', action='store_true',
                       help='Test mode - process only 5 documents')

    args = parser.parse_args()

    # Initialize enhancer
    enhancer = MetadataEnhancer()

    try:
        # Connect to services
        if not enhancer.connect():
            logger.error("Failed to connect to required services")
            sys.exit(1)

        # Execute enhancement
        if args.enhance_all or args.test:
            limit = 5 if args.test else args.limit
            if enhancer.enhance_all_documents(batch_size=args.batch_size, limit=limit):
                logger.info("✅ Enhancement completed successfully")
            else:
                logger.error("❌ Enhancement completed with errors")
                sys.exit(1)
        else:
            parser.print_help()

    finally:
        enhancer.close()


if __name__ == '__main__':
    main()