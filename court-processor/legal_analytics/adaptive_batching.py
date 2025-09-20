"""
Adaptive Batch Sizing Strategy for Legal Analytics

Dynamically optimizes batch sizes based on:
- Available system memory
- Document characteristics (size, complexity)
- Operation type (graph building, clustering, etc.)
- Historical performance data
"""

import psutil
import time
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import math
from collections import deque
import asyncio

logger = logging.getLogger(__name__)

class OperationType(Enum):
    """Different types of operations with different resource requirements"""
    DOCUMENT_FETCH = "document_fetch"
    GRAPH_BUILDING = "graph_building"
    TOPIC_CLUSTERING = "topic_clustering"
    CITATION_ANALYSIS = "citation_analysis"
    EMBEDDING_GENERATION = "embedding_generation"
    SIMILARITY_COMPUTATION = "similarity_computation"

@dataclass
class BatchMetrics:
    """Metrics for a completed batch operation"""
    operation_type: OperationType
    batch_size: int
    processing_time: float
    memory_used_mb: float
    documents_processed: int
    success: bool
    error_message: Optional[str] = None

@dataclass
class SystemResources:
    """Current system resource availability"""
    available_memory_gb: float
    cpu_usage_percent: float
    memory_usage_percent: float
    estimated_doc_size_mb: float = 0.1  # Conservative estimate

    @classmethod
    def get_current(cls) -> 'SystemResources':
        """Get current system resource status"""
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=0.1)

        return cls(
            available_memory_gb=memory.available / (1024**3),
            cpu_usage_percent=cpu_percent,
            memory_usage_percent=memory.percent
        )

@dataclass
class BatchSizeConfig:
    """Configuration for batch size calculation"""
    operation_type: OperationType
    min_batch_size: int = 10
    max_batch_size: int = 1000
    target_memory_usage_mb: float = 500  # Target memory usage per batch
    safety_factor: float = 0.8  # Conservative factor for memory usage
    performance_weight: float = 0.6  # Weight for performance vs safety

class AdaptiveBatchSizer:
    """
    Adaptive batch sizing engine that learns from performance history
    and adjusts batch sizes based on system resources and operation type
    """

    def __init__(self, max_history_size: int = 100):
        self.max_history_size = max_history_size
        self.batch_history: Dict[OperationType, deque] = {
            op_type: deque(maxlen=max_history_size)
            for op_type in OperationType
        }
        self.optimal_sizes: Dict[OperationType, int] = {}
        self.last_adjustment = {}

    def calculate_optimal_batch_size(
        self,
        operation_type: OperationType,
        config: Optional[BatchSizeConfig] = None,
        estimated_doc_count: Optional[int] = None
    ) -> int:
        """
        Calculate optimal batch size for the given operation type

        Args:
            operation_type: Type of operation to optimize for
            config: Optional configuration override
            estimated_doc_count: Estimated total documents to process
        """
        if config is None:
            config = self._get_default_config(operation_type)

        # Get current system resources
        resources = SystemResources.get_current()

        # Calculate base batch size from memory constraints
        memory_based_size = self._calculate_memory_based_size(config, resources)

        # Apply performance adjustments based on history
        performance_adjusted_size = self._apply_performance_adjustments(
            operation_type, memory_based_size, config
        )

        # Apply system load adjustments
        load_adjusted_size = self._apply_load_adjustments(
            performance_adjusted_size, resources
        )

        # Apply document count constraints
        final_size = self._apply_count_constraints(
            load_adjusted_size, estimated_doc_count, config
        )

        logger.debug(
            f"Batch size calculation for {operation_type.value}: "
            f"memory_based={memory_based_size}, "
            f"performance_adjusted={performance_adjusted_size}, "
            f"load_adjusted={load_adjusted_size}, "
            f"final={final_size}"
        )

        return final_size

    def _get_default_config(self, operation_type: OperationType) -> BatchSizeConfig:
        """Get default configuration for operation type"""
        configs = {
            OperationType.DOCUMENT_FETCH: BatchSizeConfig(
                operation_type=operation_type,
                min_batch_size=50,
                max_batch_size=500,
                target_memory_usage_mb=200,
                safety_factor=0.9
            ),
            OperationType.GRAPH_BUILDING: BatchSizeConfig(
                operation_type=operation_type,
                min_batch_size=20,
                max_batch_size=200,
                target_memory_usage_mb=800,
                safety_factor=0.7
            ),
            OperationType.TOPIC_CLUSTERING: BatchSizeConfig(
                operation_type=operation_type,
                min_batch_size=30,
                max_batch_size=300,
                target_memory_usage_mb=600,
                safety_factor=0.8
            ),
            OperationType.CITATION_ANALYSIS: BatchSizeConfig(
                operation_type=operation_type,
                min_batch_size=100,
                max_batch_size=1000,
                target_memory_usage_mb=300,
                safety_factor=0.85
            ),
            OperationType.EMBEDDING_GENERATION: BatchSizeConfig(
                operation_type=operation_type,
                min_batch_size=5,
                max_batch_size=50,
                target_memory_usage_mb=1000,
                safety_factor=0.6
            ),
            OperationType.SIMILARITY_COMPUTATION: BatchSizeConfig(
                operation_type=operation_type,
                min_batch_size=10,
                max_batch_size=100,
                target_memory_usage_mb=400,
                safety_factor=0.75
            )
        }
        return configs.get(operation_type, BatchSizeConfig(operation_type))

    def _calculate_memory_based_size(
        self, config: BatchSizeConfig, resources: SystemResources
    ) -> int:
        """Calculate batch size based on available memory"""
        # Available memory with safety factor
        usable_memory_mb = (
            resources.available_memory_gb * 1024 * config.safety_factor
        )

        # Target batch size based on memory
        if config.target_memory_usage_mb > 0:
            target_size = int(usable_memory_mb / config.target_memory_usage_mb)
        else:
            # Fallback calculation
            estimated_docs_per_gb = 1000 / resources.estimated_doc_size_mb
            target_size = int(resources.available_memory_gb * estimated_docs_per_gb * 0.5)

        return max(config.min_batch_size, min(target_size, config.max_batch_size))

    def _apply_performance_adjustments(
        self, operation_type: OperationType, base_size: int, config: BatchSizeConfig
    ) -> int:
        """Apply adjustments based on historical performance"""
        history = self.batch_history[operation_type]

        if len(history) < 3:
            return base_size

        # Analyze recent performance
        recent_metrics = list(history)[-5:]  # Last 5 batches
        successful_metrics = [m for m in recent_metrics if m.success]

        if not successful_metrics:
            # If recent batches failed, be more conservative
            return max(config.min_batch_size, int(base_size * 0.7))

        # Calculate performance indicators
        avg_time_per_doc = sum(
            m.processing_time / m.documents_processed
            for m in successful_metrics
        ) / len(successful_metrics)

        avg_memory_per_doc = sum(
            m.memory_used_mb / m.documents_processed
            for m in successful_metrics
        ) / len(successful_metrics)

        # Find optimal size from history
        if operation_type in self.optimal_sizes:
            historical_optimal = self.optimal_sizes[operation_type]
            # Blend historical optimal with current calculation
            blended_size = int(
                base_size * (1 - config.performance_weight) +
                historical_optimal * config.performance_weight
            )
            return max(config.min_batch_size, min(blended_size, config.max_batch_size))

        return base_size

    def _apply_load_adjustments(self, base_size: int, resources: SystemResources) -> int:
        """Apply adjustments based on current system load"""
        # Reduce batch size if system is under high load
        if resources.memory_usage_percent > 80:
            load_factor = 0.6
        elif resources.memory_usage_percent > 60:
            load_factor = 0.8
        elif resources.cpu_usage_percent > 80:
            load_factor = 0.7
        else:
            load_factor = 1.0

        return max(10, int(base_size * load_factor))

    def _apply_count_constraints(
        self, base_size: int, estimated_doc_count: Optional[int], config: BatchSizeConfig
    ) -> int:
        """Apply constraints based on total document count"""
        if estimated_doc_count is None:
            return base_size

        # For small datasets, use smaller batches to ensure parallelization
        if estimated_doc_count < 100:
            return min(base_size, max(10, estimated_doc_count // 4))

        # For very large datasets, consider chunking strategy
        if estimated_doc_count > 10000:
            # Use larger batches for efficiency, but cap at max
            return min(config.max_batch_size, max(base_size, 200))

        return base_size

    def record_batch_performance(self, metrics: BatchMetrics) -> None:
        """Record performance metrics for a completed batch"""
        self.batch_history[metrics.operation_type].append(metrics)
        self._update_optimal_size(metrics.operation_type)

    def _update_optimal_size(self, operation_type: OperationType) -> None:
        """Update optimal size based on performance history"""
        history = self.batch_history[operation_type]

        if len(history) < 5:
            return

        # Find the batch size with best throughput among successful batches
        successful_batches = [m for m in history if m.success]

        if not successful_batches:
            return

        # Calculate throughput (docs per second) for each batch
        throughputs = [
            (m.documents_processed / m.processing_time, m.batch_size)
            for m in successful_batches
            if m.processing_time > 0
        ]

        if throughputs:
            # Find batch size with highest throughput
            best_throughput, best_size = max(throughputs, key=lambda x: x[0])
            self.optimal_sizes[operation_type] = best_size
            logger.debug(f"Updated optimal size for {operation_type.value}: {best_size}")

    async def adaptive_batch_processor(
        self,
        operation_type: OperationType,
        items: List[Any],
        processor_func: callable,
        config: Optional[BatchSizeConfig] = None
    ) -> List[Any]:
        """
        Process items using adaptive batch sizing with performance monitoring

        Args:
            operation_type: Type of operation being performed
            items: List of items to process
            processor_func: Async function to process each batch
            config: Optional batch size configuration
        """
        results = []
        total_items = len(items)
        processed_count = 0

        while processed_count < total_items:
            # Calculate optimal batch size for remaining items
            remaining_items = total_items - processed_count
            batch_size = self.calculate_optimal_batch_size(
                operation_type, config, remaining_items
            )

            # Extract batch
            end_idx = min(processed_count + batch_size, total_items)
            batch = items[processed_count:end_idx]

            # Process batch with performance monitoring
            start_time = time.time()
            start_memory = psutil.Process().memory_info().rss / (1024 * 1024)

            try:
                batch_results = await processor_func(batch)
                success = True
                error_message = None
                results.extend(batch_results)

            except Exception as e:
                success = False
                error_message = str(e)
                logger.error(f"Batch processing failed: {e}")
                # For failed batches, try smaller size
                if batch_size > 10:
                    smaller_batch_size = max(10, batch_size // 2)
                    logger.info(f"Retrying with smaller batch size: {smaller_batch_size}")
                    smaller_batch = batch[:smaller_batch_size]
                    try:
                        batch_results = await processor_func(smaller_batch)
                        results.extend(batch_results)
                        processed_count += len(smaller_batch)
                        continue
                    except Exception as retry_e:
                        logger.error(f"Retry also failed: {retry_e}")
                        raise
                else:
                    raise

            finally:
                # Record performance metrics
                end_time = time.time()
                end_memory = psutil.Process().memory_info().rss / (1024 * 1024)

                metrics = BatchMetrics(
                    operation_type=operation_type,
                    batch_size=len(batch),
                    processing_time=end_time - start_time,
                    memory_used_mb=end_memory - start_memory,
                    documents_processed=len(batch),
                    success=success,
                    error_message=error_message
                )

                self.record_batch_performance(metrics)

            processed_count = end_idx

        return results

    def get_performance_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get performance summary for all operation types"""
        summary = {}

        for op_type, history in self.batch_history.items():
            if not history:
                continue

            successful = [m for m in history if m.success]
            if not successful:
                continue

            avg_time = sum(m.processing_time for m in successful) / len(successful)
            avg_throughput = sum(
                m.documents_processed / m.processing_time
                for m in successful
            ) / len(successful)

            summary[op_type.value] = {
                "total_batches": len(history),
                "successful_batches": len(successful),
                "avg_processing_time": avg_time,
                "avg_throughput_docs_per_sec": avg_throughput,
                "optimal_batch_size": self.optimal_sizes.get(op_type, "not_determined")
            }

        return summary

# Global adaptive batch sizer instance
_batch_sizer = AdaptiveBatchSizer()

def get_batch_sizer() -> AdaptiveBatchSizer:
    """Get the global batch sizer instance"""
    return _batch_sizer

# Convenience functions
def get_optimal_batch_size(operation_type: OperationType, **kwargs) -> int:
    """Get optimal batch size for operation type"""
    return _batch_sizer.calculate_optimal_batch_size(operation_type, **kwargs)

async def process_with_adaptive_batching(
    operation_type: OperationType,
    items: List[Any],
    processor_func: callable,
    **kwargs
) -> List[Any]:
    """Process items with adaptive batching"""
    return await _batch_sizer.adaptive_batch_processor(
        operation_type, items, processor_func, **kwargs
    )