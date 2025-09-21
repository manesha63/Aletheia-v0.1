"""
Simplified Adaptive Batch Sizing with Retry Logic and Circuit Breaker

Optimizes batch sizes based on simple rules:
- Memory-based sizing
- Load-based adjustments
- Operation-specific configurations
Includes robust error recovery with exponential backoff and circuit breaker.
"""

import psutil
import time
import logging
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import random
from collections import deque
from datetime import datetime, timedelta

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
class RetryConfig:
    """Configuration for retry logic"""
    max_retries: int = 3
    initial_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True  # Add randomness to prevent thundering herd

@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5  # Number of failures to open circuit
    success_threshold: int = 2  # Number of successes to close circuit
    timeout: float = 60.0  # Seconds before attempting to close circuit
    half_open_max_attempts: int = 3  # Max attempts in half-open state

class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered

@dataclass
class CircuitBreaker:
    """Circuit breaker implementation for batch processing"""
    config: CircuitBreakerConfig
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    half_open_attempts: int = 0

    def record_success(self):
        """Record a successful operation"""
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitState.CLOSED
                self.success_count = 0
                self.half_open_attempts = 0
                logger.info("Circuit breaker closed - service recovered")

    def record_failure(self):
        """Record a failed operation"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()

        if self.state == CircuitState.HALF_OPEN:
            self.half_open_attempts += 1
            if self.half_open_attempts >= self.config.half_open_max_attempts:
                self.state = CircuitState.OPEN
                logger.warning("Circuit breaker reopened after half-open failures")

        elif self.state == CircuitState.CLOSED:
            if self.failure_count >= self.config.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(f"Circuit breaker opened after {self.failure_count} failures")

    def should_attempt(self) -> bool:
        """Check if request should be attempted"""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if self.last_failure_time:
                time_since_failure = (datetime.now() - self.last_failure_time).total_seconds()
                if time_since_failure > self.config.timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_attempts = 0
                    self.success_count = 0
                    logger.info("Circuit breaker half-open - testing recovery")
                    return True
            return False

        # HALF_OPEN state
        return self.half_open_attempts < self.config.half_open_max_attempts

@dataclass
class BatchConfig:
    """Simplified batch configuration"""
    operation_type: OperationType
    min_size: int = 10
    max_size: int = 1000
    target_memory_mb: int = 500  # Realistic memory target

    # Retry configuration
    retry_config: RetryConfig = field(default_factory=RetryConfig)

    # Circuit breaker configuration
    circuit_breaker_config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)

class SimplifiedAdaptiveBatchSizer:
    """
    Simplified adaptive batch sizing with retry logic and circuit breaker
    """

    # Operation-specific default configurations
    OPERATION_CONFIGS = {
        OperationType.DOCUMENT_FETCH: BatchConfig(
            operation_type=OperationType.DOCUMENT_FETCH,
            min_size=50, max_size=500, target_memory_mb=200
        ),
        OperationType.GRAPH_BUILDING: BatchConfig(
            operation_type=OperationType.GRAPH_BUILDING,
            min_size=20, max_size=200, target_memory_mb=800
        ),
        OperationType.TOPIC_CLUSTERING: BatchConfig(
            operation_type=OperationType.TOPIC_CLUSTERING,
            min_size=30, max_size=300, target_memory_mb=600
        ),
        OperationType.CITATION_ANALYSIS: BatchConfig(
            operation_type=OperationType.CITATION_ANALYSIS,
            min_size=50, max_size=500, target_memory_mb=300
        ),
        OperationType.EMBEDDING_GENERATION: BatchConfig(
            operation_type=OperationType.EMBEDDING_GENERATION,
            min_size=5, max_size=50, target_memory_mb=500  # Realistic for MiniLM
        ),
        OperationType.SIMILARITY_COMPUTATION: BatchConfig(
            operation_type=OperationType.SIMILARITY_COMPUTATION,
            min_size=10, max_size=100, target_memory_mb=400
        )
    }

    def __init__(self):
        self.circuit_breakers: Dict[OperationType, CircuitBreaker] = {}
        self.recent_sizes: Dict[OperationType, deque] = {}

        # Initialize circuit breakers and history for each operation
        for op_type in OperationType:
            config = self.OPERATION_CONFIGS.get(op_type, BatchConfig(op_type))
            self.circuit_breakers[op_type] = CircuitBreaker(config.circuit_breaker_config)
            self.recent_sizes[op_type] = deque(maxlen=10)

    def calculate_batch_size(
        self,
        operation_type: OperationType,
        available_items: int = None
    ) -> int:
        """
        Calculate optimal batch size using simple rules
        """
        config = self.OPERATION_CONFIGS.get(operation_type, BatchConfig(operation_type))

        # Rule 1: Memory-based sizing
        memory = psutil.virtual_memory()
        available_mb = memory.available / (1024 * 1024)
        memory_based_size = int(available_mb / config.target_memory_mb * 0.5)  # Conservative

        # Rule 2: System load adjustment
        if memory.percent > 80:
            load_factor = 0.5
        elif memory.percent > 60:
            load_factor = 0.7
        else:
            load_factor = 1.0

        adjusted_size = int(memory_based_size * load_factor)

        # Rule 3: Apply configured bounds
        batch_size = max(config.min_size, min(adjusted_size, config.max_size))

        # Rule 4: Don't exceed available items
        if available_items:
            batch_size = min(batch_size, available_items)

        # Store for history
        self.recent_sizes[operation_type].append(batch_size)

        return batch_size

    async def _process_batch_with_retry(
        self,
        batch: List[Any],
        processor_func: callable,
        config: BatchConfig,
        operation_type: OperationType
    ) -> Tuple[bool, Optional[List[Any]], Optional[str]]:
        """
        Process a single batch with exponential backoff retry
        """
        retry_config = config.retry_config
        last_exception = None

        for attempt in range(retry_config.max_retries + 1):
            try:
                # Check circuit breaker
                if not self.circuit_breakers[operation_type].should_attempt():
                    raise Exception("Circuit breaker is open - service unavailable")

                # Process the batch
                results = await processor_func(batch)

                # Record success
                self.circuit_breakers[operation_type].record_success()

                return True, results, None

            except Exception as e:
                last_exception = e
                self.circuit_breakers[operation_type].record_failure()

                if attempt < retry_config.max_retries:
                    # Calculate delay with exponential backoff
                    delay = min(
                        retry_config.initial_delay * (retry_config.exponential_base ** attempt),
                        retry_config.max_delay
                    )

                    # Add jitter to prevent thundering herd
                    if retry_config.jitter:
                        delay *= (0.5 + random.random())

                    logger.warning(
                        f"Batch processing failed (attempt {attempt + 1}/{retry_config.max_retries + 1}), "
                        f"retrying in {delay:.2f}s: {e}"
                    )

                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Batch processing failed after all retries: {e}")

        return False, None, str(last_exception)

    async def process_with_adaptive_batching(
        self,
        operation_type: OperationType,
        items: List[Any],
        processor_func: callable,
        isolate_failures: bool = True
    ) -> Tuple[List[Any], List[Any]]:
        """
        Process items with adaptive batching, retry logic, and failure isolation

        Args:
            operation_type: Type of operation
            items: Items to process
            processor_func: Async function to process each batch
            isolate_failures: If True, isolate failed items and continue

        Returns:
            Tuple of (successful_results, failed_items)
        """
        config = self.OPERATION_CONFIGS.get(operation_type, BatchConfig(operation_type))

        successful_results = []
        failed_items = []
        processed_count = 0
        total_items = len(items)

        while processed_count < total_items:
            # Calculate batch size for remaining items
            remaining = total_items - processed_count
            batch_size = self.calculate_batch_size(operation_type, remaining)

            # Get the batch
            batch = items[processed_count:processed_count + batch_size]

            # Process with retry logic
            success, results, error = await self._process_batch_with_retry(
                batch, processor_func, config, operation_type
            )

            if success and results is not None:
                successful_results.extend(results)
                processed_count += len(batch)
            else:
                if isolate_failures:
                    # If batch failed, try processing items individually
                    logger.info(f"Batch failed, attempting individual processing for {len(batch)} items")

                    for item in batch:
                        item_success, item_results, _ = await self._process_batch_with_retry(
                            [item], processor_func, config, operation_type
                        )

                        if item_success and item_results:
                            successful_results.extend(item_results)
                        else:
                            failed_items.append(item)

                    processed_count += len(batch)
                else:
                    # Fail fast - don't continue processing
                    failed_items.extend(batch)
                    failed_items.extend(items[processed_count + batch_size:])
                    break

        if failed_items:
            logger.warning(f"Processing completed with {len(failed_items)} failed items")

        return successful_results, failed_items

    def get_circuit_status(self) -> Dict[str, str]:
        """Get status of all circuit breakers"""
        return {
            op_type.value: self.circuit_breakers[op_type].state.value
            for op_type in OperationType
        }

    def reset_circuit_breaker(self, operation_type: OperationType):
        """Manually reset a circuit breaker"""
        config = self.OPERATION_CONFIGS.get(operation_type, BatchConfig(operation_type))
        self.circuit_breakers[operation_type] = CircuitBreaker(config.circuit_breaker_config)
        logger.info(f"Circuit breaker reset for {operation_type.value}")

# Global instance
_simplified_batch_sizer = SimplifiedAdaptiveBatchSizer()

def get_batch_sizer() -> SimplifiedAdaptiveBatchSizer:
    """Get the global simplified batch sizer instance"""
    return _simplified_batch_sizer

# Convenience functions
async def process_with_retry_and_batching(
    operation_type: OperationType,
    items: List[Any],
    processor_func: callable,
    isolate_failures: bool = True
) -> Tuple[List[Any], List[Any]]:
    """
    Process items with adaptive batching, retry logic, and circuit breaker

    Returns: (successful_results, failed_items)
    """
    return await _simplified_batch_sizer.process_with_adaptive_batching(
        operation_type, items, processor_func, isolate_failures
    )

def get_circuit_breaker_status() -> Dict[str, str]:
    """Get the status of all circuit breakers"""
    return _simplified_batch_sizer.get_circuit_status()

def calculate_optimal_batch_size(
    operation_type: OperationType,
    available_items: int = None
) -> int:
    """Calculate the optimal batch size for an operation"""
    return _simplified_batch_sizer.calculate_batch_size(operation_type, available_items)

# Backward compatibility alias
AdaptiveBatchSizer = SimplifiedAdaptiveBatchSizer