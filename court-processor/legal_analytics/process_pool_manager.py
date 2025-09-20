"""
Thread-Safe Process Pool Manager for Legal Analytics

Provides centralized, thread-safe management of process pools for CPU-intensive
operations like embedding generation. Includes adaptive scaling and proper cleanup.
"""

import threading
import concurrent.futures
import logging
import asyncio
import atexit
from typing import Dict, Optional, Any, Callable
from contextlib import contextmanager
from dataclasses import dataclass
import os
import psutil

logger = logging.getLogger(__name__)

@dataclass
class PoolConfig:
    """Configuration for process pools"""
    max_workers: int = 2
    initializer: Optional[Callable] = None
    initargs: tuple = ()
    name: str = "default"

class ProcessPoolManager:
    """
    Thread-safe singleton manager for process pools

    Features:
    - Thread-safe initialization and access
    - Adaptive worker scaling based on system resources
    - Automatic cleanup on shutdown
    - Per-service pool isolation
    - Health monitoring and recovery
    """

    _instance = None
    _lock = threading.Lock()
    _pools: Dict[str, concurrent.futures.ProcessPoolExecutor] = {}
    _pool_configs: Dict[str, PoolConfig] = {}
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    self._pools = {}
                    self._pool_configs = {}
                    self._initialized = True
                    # Register cleanup on exit
                    atexit.register(self.cleanup_all)
                    logger.info("ProcessPoolManager initialized")

    @classmethod
    def get_optimal_workers(cls, pool_type: str = "cpu_intensive") -> int:
        """Calculate optimal number of workers based on system resources"""
        try:
            cpu_count = os.cpu_count() or 2
            available_memory_gb = psutil.virtual_memory().available / (1024**3)

            if pool_type == "embedding":
                # Embedding models are memory-intensive
                # Estimate ~2GB per worker for sentence transformers
                memory_based_limit = max(1, int(available_memory_gb / 2))
                return min(cpu_count // 2, memory_based_limit, 3)  # Cap at 3 for stability

            elif pool_type == "cpu_intensive":
                # General CPU-intensive work
                return min(cpu_count, 4)  # Cap at 4 for most operations

            else:
                return 2  # Conservative default

        except Exception as e:
            logger.warning(f"Failed to determine optimal workers: {e}")
            return 2  # Safe fallback

    def get_or_create_pool(
        self,
        pool_name: str,
        config: Optional[PoolConfig] = None,
        pool_type: str = "cpu_intensive"
    ) -> concurrent.futures.ProcessPoolExecutor:
        """
        Get existing pool or create new one with thread safety

        Args:
            pool_name: Unique identifier for the pool
            config: Pool configuration (if None, creates default)
            pool_type: Type hint for optimal worker calculation
        """
        with self._lock:
            if pool_name in self._pools:
                # Check if pool is healthy
                if self._is_pool_healthy(pool_name):
                    return self._pools[pool_name]
                else:
                    # Clean up unhealthy pool and recreate
                    logger.warning(f"Pool {pool_name} appears unhealthy, recreating")
                    self._cleanup_pool(pool_name)

            # Create new pool
            if config is None:
                config = PoolConfig(
                    max_workers=self.get_optimal_workers(pool_type),
                    name=pool_name
                )

            try:
                pool = concurrent.futures.ProcessPoolExecutor(
                    max_workers=config.max_workers,
                    initializer=config.initializer,
                    initargs=config.initargs
                )

                self._pools[pool_name] = pool
                self._pool_configs[pool_name] = config

                logger.info(f"Created process pool '{pool_name}' with {config.max_workers} workers")
                return pool

            except Exception as e:
                logger.error(f"Failed to create process pool '{pool_name}': {e}")
                raise

    def _is_pool_healthy(self, pool_name: str) -> bool:
        """Check if a pool is still healthy and responsive"""
        if pool_name not in self._pools:
            return False

        pool = self._pools[pool_name]

        # Check if pool is shutdown
        if pool._shutdown:
            return False

        # Could add more health checks here (e.g., submit a test task)
        return True

    def _cleanup_pool(self, pool_name: str) -> None:
        """Clean up a specific pool"""
        if pool_name in self._pools:
            try:
                pool = self._pools[pool_name]
                pool.shutdown(wait=True)
                logger.info(f"Cleaned up process pool '{pool_name}'")
            except Exception as e:
                logger.error(f"Error cleaning up pool '{pool_name}': {e}")
            finally:
                del self._pools[pool_name]
                if pool_name in self._pool_configs:
                    del self._pool_configs[pool_name]

    def cleanup_all(self) -> None:
        """Clean up all pools - called on shutdown"""
        with self._lock:
            pool_names = list(self._pools.keys())
            for pool_name in pool_names:
                self._cleanup_pool(pool_name)
            logger.info("All process pools cleaned up")

    @contextmanager
    def get_pool_context(self, pool_name: str, config: Optional[PoolConfig] = None):
        """Context manager for automatic pool cleanup"""
        pool = self.get_or_create_pool(pool_name, config)
        try:
            yield pool
        finally:
            # Pool stays alive for reuse, but could add cleanup logic here if needed
            pass

    async def submit_task(
        self,
        pool_name: str,
        func: Callable,
        *args,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Any:
        """
        Submit a task to the specified pool with async interface

        Args:
            pool_name: Name of the pool to use
            func: Function to execute
            *args: Function arguments
            timeout: Optional timeout in seconds
            **kwargs: Keyword arguments for the function
        """
        pool = self.get_or_create_pool(pool_name)
        loop = asyncio.get_event_loop()

        try:
            # Submit task and wait for completion
            future = pool.submit(func, *args, **kwargs)
            result = await asyncio.wait_for(
                loop.run_in_executor(None, future.result),
                timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            logger.error(f"Task in pool '{pool_name}' timed out after {timeout}s")
            raise
        except Exception as e:
            logger.error(f"Task in pool '{pool_name}' failed: {e}")
            raise

    def get_pool_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all pools"""
        stats = {}
        with self._lock:
            for name, pool in self._pools.items():
                config = self._pool_configs.get(name, PoolConfig())
                stats[name] = {
                    "max_workers": config.max_workers,
                    "active": not pool._shutdown,
                    "healthy": self._is_pool_healthy(name)
                }
        return stats

# Global instance
_pool_manager = ProcessPoolManager()

# Convenience functions for common use cases
def get_embedding_pool() -> concurrent.futures.ProcessPoolExecutor:
    """Get the embedding-specific process pool"""
    def _init_embedding_worker():
        """Initialize embedding model in worker process"""
        global _embedding_model
        if '_embedding_model' not in globals():
            try:
                from sentence_transformers import SentenceTransformer
                _embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
            except ImportError:
                _embedding_model = None

    config = PoolConfig(
        max_workers=ProcessPoolManager.get_optimal_workers("embedding"),
        initializer=_init_embedding_worker,
        name="embedding"
    )

    return _pool_manager.get_or_create_pool("embedding", config, "embedding")

def get_analytics_pool() -> concurrent.futures.ProcessPoolExecutor:
    """Get the general analytics process pool"""
    return _pool_manager.get_or_create_pool("analytics", pool_type="cpu_intensive")

async def encode_text_async(text: str, timeout: float = 30.0) -> list:
    """Async wrapper for text encoding"""
    def _encode_worker(text: str) -> list:
        global _embedding_model
        if _embedding_model is None:
            raise RuntimeError("Embedding model not initialized in worker")
        embedding = _embedding_model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    return await _pool_manager.submit_task(
        "embedding",
        _encode_worker,
        text,
        timeout=timeout
    )

def cleanup_pools():
    """Cleanup all pools - for manual cleanup"""
    _pool_manager.cleanup_all()

def get_pool_manager() -> ProcessPoolManager:
    """Get the global pool manager instance"""
    return _pool_manager