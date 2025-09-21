"""
Resource Management and Cleanup Context Managers

Provides context managers and utilities for proper resource management across
all legal analytics services. Ensures cleanup of connections, pools, and resources.
"""

import asyncio
import logging
import signal
import sys
import atexit
from contextlib import asynccontextmanager, contextmanager
from typing import Dict, List, Optional, Any, AsyncGenerator, Generator
import concurrent.futures
from dataclasses import dataclass
import weakref
import threading
import time

logger = logging.getLogger(__name__)

@dataclass
class ResourceInfo:
    """Information about a managed resource"""
    name: str
    resource_type: str
    created_at: float
    cleanup_func: callable
    auto_cleanup: bool = True

class ResourceTracker:
    """Tracks and manages cleanup of all resources with thread-safe operations"""

    def __init__(self):
        self._resources: Dict[str, ResourceInfo] = {}
        self._lock = threading.RLock()  # Use RLock for reentrant locking
        self._shutdown_lock = threading.Lock()  # Separate lock for shutdown
        self._shutdown_initiated = threading.Event()  # Atomic flag for shutdown state
        self._cleanup_handlers = []
        self._signal_handlers_registered = False
        self._cleanup_timeout = 30  # seconds

        # Register signal handlers for graceful shutdown (thread-safe)
        self._register_signal_handlers()
        atexit.register(self._atexit_handler)

    def _register_signal_handlers(self):
        """Thread-safe signal handler registration"""
        with self._shutdown_lock:
            if not self._signal_handlers_registered:
                try:
                    signal.signal(signal.SIGTERM, self._signal_handler)
                    signal.signal(signal.SIGINT, self._signal_handler)
                    self._signal_handlers_registered = True
                except Exception as e:
                    # Signal registration can fail in some contexts (e.g., threads)
                    logger.debug(f"Could not register signal handlers: {e}")

    def register_resource(
        self,
        name: str,
        resource: Any,
        cleanup_func: callable,
        resource_type: str = "generic",
        auto_cleanup: bool = True
    ):
        """Register a resource for tracking and cleanup"""
        # Check shutdown flag without acquiring lock first (optimization)
        if self._shutdown_initiated.is_set():
            logger.warning(f"Cannot register resource {name} during shutdown")
            return

        with self._lock:
            # Double-check after acquiring lock
            if self._shutdown_initiated.is_set():
                logger.warning(f"Cannot register resource {name} during shutdown")
                return

            self._resources[name] = ResourceInfo(
                name=name,
                resource_type=resource_type,
                created_at=time.time(),
                cleanup_func=cleanup_func,
                auto_cleanup=auto_cleanup
            )

            logger.debug(f"Registered resource: {name} ({resource_type})")

    def unregister_resource(self, name: str):
        """Unregister a resource (usually after manual cleanup)"""
        with self._lock:
            if name in self._resources:
                del self._resources[name]
                logger.debug(f"Unregistered resource: {name}")

    def cleanup_resource(self, name: str) -> bool:
        """Cleanup a specific resource"""
        with self._lock:
            if name not in self._resources:
                return False

            resource_info = self._resources.pop(name, None)
            if not resource_info:
                return False

        # Perform cleanup outside of lock to prevent deadlocks
        try:
            resource_info.cleanup_func()
            logger.info(f"Cleaned up resource: {name}")
            return True
        except Exception as e:
            logger.error(f"Failed to cleanup resource {name}: {e}")
            return False

    def cleanup_all(self, timeout: Optional[float] = None):
        """Cleanup all registered resources with timeout and thread safety"""
        # Use atomic operation to check and set shutdown flag
        if self._shutdown_initiated.is_set():
            logger.debug("Cleanup already initiated, skipping duplicate call")
            return

        with self._shutdown_lock:
            # Double-check after acquiring lock
            if self._shutdown_initiated.is_set():
                return

            # Atomically set shutdown flag
            self._shutdown_initiated.set()

        logger.info("Starting resource cleanup...")

        # Use timeout if provided, otherwise use default
        cleanup_timeout = timeout or self._cleanup_timeout
        start_time = time.time()

        # Get resources to cleanup (snapshot to avoid holding lock)
        with self._lock:
            resources_to_cleanup = list(self._resources.values())
            resources_to_cleanup.reverse()  # Cleanup in reverse order

        # Cleanup resources with timeout check
        for resource_info in resources_to_cleanup:
            if time.time() - start_time > cleanup_timeout:
                logger.warning(f"Cleanup timeout reached, skipping remaining resources")
                break

            if resource_info.auto_cleanup:
                try:
                    # Create a thread for each cleanup with its own timeout
                    cleanup_thread = threading.Thread(
                        target=self._cleanup_with_timeout,
                        args=(resource_info,),
                        daemon=True
                    )
                    cleanup_thread.start()
                    cleanup_thread.join(timeout=min(5.0, cleanup_timeout - (time.time() - start_time)))

                    if cleanup_thread.is_alive():
                        logger.warning(f"Cleanup timeout for {resource_info.name}, continuing...")
                except Exception as e:
                    logger.error(f"Cleanup failed for {resource_info.name}: {e}")

        # Clear remaining resources
        with self._lock:
            self._resources.clear()

        # Run additional cleanup handlers with timeout
        remaining_time = cleanup_timeout - (time.time() - start_time)
        if remaining_time > 0:
            for handler in self._cleanup_handlers:
                try:
                    handler_thread = threading.Thread(target=handler, daemon=True)
                    handler_thread.start()
                    handler_thread.join(timeout=min(2.0, remaining_time))

                    if handler_thread.is_alive():
                        logger.warning(f"Cleanup handler timeout, continuing...")
                except Exception as e:
                    logger.error(f"Cleanup handler failed: {e}")

        logger.info("Resource cleanup completed")

    def _cleanup_with_timeout(self, resource_info: ResourceInfo):
        """Execute cleanup function with error handling"""
        try:
            resource_info.cleanup_func()
            logger.debug(f"Cleaned up: {resource_info.name}")
        except Exception as e:
            logger.error(f"Cleanup failed for {resource_info.name}: {e}")

    def add_cleanup_handler(self, handler: callable):
        """Add a custom cleanup handler"""
        with self._lock:
            self._cleanup_handlers.append(handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals in a thread-safe manner"""
        # Avoid recursive signal handling
        signal.signal(signum, signal.SIG_DFL)

        logger.info(f"Received signal {signum}, initiating cleanup...")

        # Start cleanup in a separate thread to avoid signal handler limitations
        cleanup_thread = threading.Thread(target=self.cleanup_all, daemon=False)
        cleanup_thread.start()

        # Wait for cleanup with timeout
        cleanup_thread.join(timeout=self._cleanup_timeout)

        if cleanup_thread.is_alive():
            logger.error("Cleanup timeout exceeded, forcing exit")

        sys.exit(0)

    def _atexit_handler(self):
        """Handler for atexit - ensures cleanup even without signals"""
        if not self._shutdown_initiated.is_set():
            self.cleanup_all(timeout=10)  # Shorter timeout for atexit

    def get_resource_summary(self) -> Dict[str, Any]:
        """Get summary of all tracked resources"""
        with self._lock:
            summary = {
                "total_resources": len(self._resources),
                "by_type": {},
                "resources": [],
                "shutdown_initiated": self._shutdown_initiated.is_set()
            }

            for name, info in self._resources.items():
                if info.resource_type not in summary["by_type"]:
                    summary["by_type"][info.resource_type] = 0
                summary["by_type"][info.resource_type] += 1

                summary["resources"].append({
                    "name": name,
                    "type": info.resource_type,
                    "age_seconds": time.time() - info.created_at,
                    "auto_cleanup": info.auto_cleanup
                })

            return summary

    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress"""
        return self._shutdown_initiated.is_set()

# Global resource tracker with thread-safe singleton pattern
_resource_tracker_lock = threading.Lock()
_resource_tracker = None

def get_resource_tracker() -> ResourceTracker:
    """Get the global resource tracker (thread-safe singleton)"""
    global _resource_tracker
    if _resource_tracker is None:
        with _resource_tracker_lock:
            if _resource_tracker is None:
                _resource_tracker = ResourceTracker()
    return _resource_tracker

@asynccontextmanager
async def elasticsearch_connection_manager(
    es_client,
    connection_name: str = "default_es"
) -> AsyncGenerator[Any, None]:
    """
    Context manager for Elasticsearch connections with automatic cleanup
    """
    tracker = get_resource_tracker()

    def cleanup_es():
        try:
            if hasattr(es_client, 'close'):
                # For async ES client
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(es_client.close())
                    else:
                        asyncio.run_coroutine_threadsafe(es_client.close(), loop)
                except Exception:
                    # Fallback for sync close
                    es_client.close()
            logger.debug(f"Elasticsearch connection {connection_name} closed")
        except Exception as e:
            logger.error(f"Failed to close ES connection {connection_name}: {e}")

    tracker.register_resource(
        connection_name,
        es_client,
        cleanup_es,
        "elasticsearch_connection"
    )

    try:
        yield es_client
    finally:
        cleanup_es()
        tracker.unregister_resource(connection_name)

@asynccontextmanager
async def scroll_context_manager(
    es_client,
    scroll_id: str,
    scroll_name: str = "default_scroll"
) -> AsyncGenerator[str, None]:
    """
    Context manager for Elasticsearch scroll operations with guaranteed cleanup
    """
    tracker = get_resource_tracker()

    async def cleanup_scroll():
        try:
            if scroll_id:
                await es_client.clear_scroll(scroll_id=scroll_id)
                logger.debug(f"Scroll {scroll_name} cleared")
        except Exception as e:
            logger.error(f"Failed to clear scroll {scroll_name}: {e}")

    tracker.register_resource(
        f"scroll_{scroll_name}",
        scroll_id,
        lambda: asyncio.create_task(cleanup_scroll()),
        "elasticsearch_scroll"
    )

    try:
        yield scroll_id
    finally:
        await cleanup_scroll()
        tracker.unregister_resource(f"scroll_{scroll_name}")

@contextmanager
def process_pool_manager(
    pool_name: str,
    max_workers: int = 2,
    initializer: Optional[callable] = None,
    initargs: tuple = ()
) -> Generator[concurrent.futures.ProcessPoolExecutor, None, None]:
    """
    Context manager for process pools with automatic cleanup
    """
    tracker = get_resource_tracker()
    pool = None

    def cleanup_pool():
        if pool:
            try:
                # Shutdown with timeout
                pool.shutdown(wait=True, timeout=10)
                logger.debug(f"Process pool {pool_name} shutdown")
            except Exception as e:
                logger.error(f"Failed to shutdown pool {pool_name}: {e}")
                # Force shutdown if graceful fails
                try:
                    pool.shutdown(wait=False)
                except Exception:
                    pass

    try:
        pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=initializer,
            initargs=initargs
        )

        tracker.register_resource(
            f"pool_{pool_name}",
            pool,
            cleanup_pool,
            "process_pool"
        )

        yield pool

    finally:
        cleanup_pool()
        tracker.unregister_resource(f"pool_{pool_name}")

@asynccontextmanager
async def analytics_service_context(
    service_name: str,
    es_client,
    **config
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Comprehensive context manager for analytics services
    """
    tracker = get_resource_tracker()

    resources = {
        "es_client": es_client,
        "service_name": service_name,
        "config": config
    }

    # Track the service context
    def cleanup_service():
        logger.debug(f"Analytics service {service_name} context cleaned up")

    tracker.register_resource(
        f"service_{service_name}",
        resources,
        cleanup_service,
        "analytics_service"
    )

    try:
        async with elasticsearch_connection_manager(es_client, f"{service_name}_es"):
            yield resources
    finally:
        cleanup_service()
        tracker.unregister_resource(f"service_{service_name}")

@asynccontextmanager
async def batch_processing_context(
    operation_name: str,
    es_client,
    batch_processor: callable,
    cleanup_on_error: bool = True
) -> AsyncGenerator[callable, None]:
    """
    Context manager for batch processing operations with error handling
    """
    tracker = get_resource_tracker()
    processed_batches = []
    failed_batches = []

    async def tracked_batch_processor(batch):
        try:
            result = await batch_processor(batch)
            processed_batches.append(len(batch))
            return result
        except Exception as e:
            failed_batches.append((len(batch), str(e)))
            if cleanup_on_error:
                logger.warning(f"Batch failed in {operation_name}: {e}")
            raise

    def cleanup_operation():
        total_processed = sum(processed_batches)
        total_failed = sum(size for size, _ in failed_batches)
        logger.info(
            f"Operation {operation_name} completed: "
            f"{total_processed} documents processed, "
            f"{total_failed} failed"
        )

    tracker.register_resource(
        f"batch_op_{operation_name}",
        {"processed": processed_batches, "failed": failed_batches},
        cleanup_operation,
        "batch_operation"
    )

    try:
        yield tracked_batch_processor
    finally:
        cleanup_operation()
        tracker.unregister_resource(f"batch_op_{operation_name}")

class ManagedAnalyticsService:
    """
    Base class for analytics services with automatic resource management
    """

    def __init__(self, service_name: str, es_client):
        self.service_name = service_name
        self.es_client = es_client
        self._active_contexts = []

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with cleanup"""
        await self.cleanup()

    async def cleanup(self):
        """Cleanup service resources"""
        for context in self._active_contexts:
            try:
                if hasattr(context, 'close'):
                    await context.close()
            except Exception as e:
                logger.error(f"Failed to cleanup context in {self.service_name}: {e}")

        self._active_contexts.clear()
        logger.debug(f"Service {self.service_name} cleaned up")

    @asynccontextmanager
    async def get_scroll_context(self, query: Dict[str, Any]):
        """Get a managed scroll context"""
        response = await self.es_client.search(
            index="court-documents",
            body=query,
            scroll="5m"
        )

        scroll_id = response["_scroll_id"]
        async with scroll_context_manager(
            self.es_client,
            scroll_id,
            f"{self.service_name}_scroll"
        ) as managed_scroll_id:
            yield response, managed_scroll_id

    async def process_with_managed_batching(
        self,
        operation_name: str,
        batch_processor: callable
    ):
        """Process batches with managed context"""
        async with batch_processing_context(
            f"{self.service_name}_{operation_name}",
            self.es_client,
            batch_processor
        ) as managed_processor:
            return managed_processor

# Convenience functions
def register_cleanup_handler(handler: callable):
    """Register a custom cleanup handler"""
    get_resource_tracker().add_cleanup_handler(handler)

def force_cleanup_all():
    """Force cleanup of all resources"""
    get_resource_tracker().cleanup_all()

def get_resource_summary() -> Dict[str, Any]:
    """Get summary of all managed resources"""
    return get_resource_tracker().get_resource_summary()

def is_shutting_down() -> bool:
    """Check if system is shutting down"""
    return get_resource_tracker().is_shutting_down()

# Decorator for automatic resource management
def with_resource_management(resource_type: str = "function"):
    """Decorator to add automatic resource management to functions"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            tracker = get_resource_tracker()
            func_name = f"{func.__module__}.{func.__name__}"

            def cleanup_func_resource():
                logger.debug(f"Function {func_name} completed")

            tracker.register_resource(
                func_name,
                func,
                cleanup_func_resource,
                resource_type
            )

            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                tracker.unregister_resource(func_name)

        return wrapper
    return decorator