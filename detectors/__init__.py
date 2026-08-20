"""速卖通违规检测器集合"""
from detectors.text_prohibited import TextProhibitedDetector
from detectors.text_contact_leak import ContactLeakDetector
from detectors.html_structure import HtmlStructureDetector
from detectors.brand_check import BrandCheckDetector
from detectors.search_cheating import SearchCheatingDetector
from detectors.image_analysis import ImageAnalysisDetector

__all__ = [
    "TextProhibitedDetector",
    "ContactLeakDetector",
    "HtmlStructureDetector",
    "BrandCheckDetector",
    "SearchCheatingDetector",
    "ImageAnalysisDetector",
]
