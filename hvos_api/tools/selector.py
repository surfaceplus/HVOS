"""
Product Selector Tool
=====================
Selects top products from HVOS Opportunity Engine based on criteria.

Uses the actual OpportunityEngine from the opportunity module.
"""

import sys
import os
import threading
from typing import List, Dict, Any, Optional

# Add HVOS paths
HVOS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OPP_DIR = os.path.join(HVOS_ROOT, "opportunity")
for _p in [OPP_DIR, HVOS_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class ProductSelector:
    """
    Product Selector Tool.
    
    Wraps OpportunityEngine to provide product selection via API.
    
    Usage:
        selector = ProductSelector()
        result = selector.select(
            category="kitchen",
            limit=10,
            min_alpha_score=5.0
        )
    """
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self._engine = None
        self._engine_lock = threading.Lock()
        self._initialized = False
        self._init_error = None
    
    def _get_engine(self):
        """Lazy initialization of OpportunityEngine with thread safety"""
        if self._engine is not None:
            return self._engine
            
        if self._init_error:
            raise self._init_error
        
        with self._engine_lock:
            # Double-check after acquiring lock
            if self._engine is not None:
                return self._engine
                
            try:
                from opportunity.opportunity_engine import OpportunityEngine
                self._engine = OpportunityEngine(config=self.config)
                self._initialized = True
            except ImportError as e:
                self._init_error = RuntimeError(
                    f"Failed to import OpportunityEngine: {e}. "
                    "Make sure opportunity_engine.py is available."
                )
                raise self._init_error
            except Exception as e:
                self._init_error = e
                raise
        
        return self._engine
    
    def select(
        self,
        category: str = "",
        limit: int = 10,
        min_alpha_score: float = 0.0,
        recommendation: str = "",
    ) -> Dict[str, Any]:
        """
        Select products from opportunity engine.
        
        Args:
            category: Category filter (kitchen, gift, pet, etc.)
            limit: Maximum number of results
            min_alpha_score: Minimum alpha score threshold
            recommendation: Filter by recommendation (INVEST, WATCH, SKIP)
            
        Returns:
            Structured result with products list and metadata
        """
        try:
            engine = self._get_engine()
            
            # Get opportunities based on category
            if category:
                opportunities = engine.get_by_category(category)
            else:
                opportunities = engine.get_top_opportunities(limit=limit * 2)  # Get more to filter
            
            # Apply filters
            filtered = []
            for opp in opportunities:
                # Alpha score filter
                if hasattr(opp, 'alpha_score') and opp.alpha_score < min_alpha_score:
                    continue
                
                # Recommendation filter
                if recommendation and hasattr(opp, 'recommendation'):
                    if opp.recommendation != recommendation:
                        continue
                
                filtered.append(opp)
                
                # Limit results
                if len(filtered) >= limit:
                    break
            
            # Convert to dict format
            products = []
            for opp in filtered:
                product = {
                    "opp_id": getattr(opp, 'opp_id', getattr(opp, 'id', '')),
                    "name": getattr(opp, 'name', getattr(opp, 'product_name', '')),
                    "category": getattr(opp, 'category', category or 'general'),
                    "alpha_score": getattr(opp, 'alpha_score', 0.0),
                    "recommendation": getattr(opp, 'recommendation', 'WATCH'),
                    "velocity": getattr(opp, 'velocity', 0.0),
                    "breadth": getattr(opp, 'breadth', 0.0),
                    "depth": getattr(opp, 'depth', 0.0),
                    "competition_gap": getattr(opp, 'competition_gap', 0.0),
                    "seasonal_fit": getattr(opp, 'seasonal_fit', 0.0),
                    "confidence": getattr(opp, 'confidence', 0.5),
                    "weighted_score": getattr(opp, 'weighted_score', 0.0),
                    "seasonal_window": getattr(opp, 'seasonal_window', ''),
                    "days_to_window": getattr(opp, 'days_to_window', 999),
                    "status": getattr(opp, 'status', 'discovered'),
                    "signals": getattr(opp, 'signals', []),
                    "signal_count": getattr(opp, 'signal_count', 0),
                    "created_at": getattr(opp, 'created_at', ''),
                }
                products.append(product)
            
            return {
                "success": True,
                "tool": "product_selector",
                "count": len(products),
                "category": category or "all",
                "products": products,
            }
            
        except Exception as e:
            return {
                "success": False,
                "tool": "product_selector",
                "error": str(e),
                "error_type": type(e).__name__,
            }
    
    def get_categories(self) -> Dict[str, Any]:
        """Get available categories"""
        return {
            "success": True,
            "tool": "product_selector",
            "categories": [
                "kitchen", "gift", "pet", "outdoor",
                "beauty", "home", "tech", "fitness"
            ]
        }