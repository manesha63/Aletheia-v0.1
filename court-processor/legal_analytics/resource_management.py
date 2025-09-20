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
    """Tracks and manages cleanup of all resources"""

    def __init__(self):
        self._resources: Dict[str, ResourceInfo] = {}
        self._lock = threading.Lock()
        self._shutdown_initiated = False
        self._cleanup_handlers = []

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        atexit.register(self.cleanup_all)

    def register_resource(
        self,
        name: str,
        resource: Any,
        cleanup_func: callable,
        resource_type: str = "generic",
        auto_cleanup: bool = True
    ):
        """Register a resource for tracking and cleanup"""
        with self._lock:
            if self._shutdown_initiated:
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

            resource_info = self._resources[name]
            try:
                resource_info.cleanup_func()
                logger.info(f"Cleaned up resource: {name}")
                del self._resources[name]
                return True
            except Exception as e:
                logger.error(f"Failed to cleanup resource {name}: {e}")
                return False

    def cleanup_all(self):
        """Cleanup all registered resources"""
        if self._shutdown_initiated:
            return

        self._shutdown_initiated = True
        logger.info("Starting resource cleanup...")

        with self._lock:
            # Cleanup in reverse order of registration
            resources_to_cleanup = list(self._resources.values())
            resources_to_cleanup.reverse()

            for resource_info in resources_to_cleanup:
                if resource_info.auto_cleanup:
                    try:
                        resource_info.cleanup_func()
                        logger.debug(f"Cleaned up: {resource_info.name}")
                    except Exception as e:
                        logger.error(f"Cleanup failed for {resource_info.name}: {e}")

            self._resources.clear()

        # Run additional cleanup handlers
        for handler in self._cleanup_handlers:
            try:
                handler()
            except Exception as e:
                logger.error(f"Cleanup handler failed: {e}")

        logger.info("Resource cleanup completed")

    def add_cleanup_handler(self, handler: callable):
        """Add a custom cleanup handler"""
        self._cleanup_handlers.append(handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, initiating cleanup...")
        self.cleanup_all()
        sys.exit(0)

    def get_resource_summary(self) -> Dict[str, Any]:
        """Get summary of all tracked resources"""
        with self._lock:
            summary = {
                "total_resources": len(self._resources),
                "by_type": {},
                "resources": []
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

# Global resource tracker
_resource_tracker = ResourceTracker()

def get_resource_tracker() -> ResourceTracker:
    """Get the global resource tracker"""
    return _resource_tracker

@asynccontextmanager
async def elasticsearch_connection_manager(
    es_client,
    connection_name: str = "default_es"
) -> AsyncGenerator[Any, None]:
    """
    Context manager for Elasticsearch connections with automatic cleanup
    """
    def cleanup_es():
        try:
            if hasattr(es_client, 'close'):
                # For async ES client
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(es_client.close())
                else:
                    loop.run_until_complete(es_client.close())
            logger.debug(f"Elasticsearch connection {connection_name} closed")
        except Exception as e:
            logger.error(f"Failed to close ES connection {connection_name}: {e}")

    _resource_tracker.register_resource(
        connection_name,
        es_client,
        cleanup_es,
        "elasticsearch_connection"
    )

    try:
        yield es_client
    finally:
        cleanup_es()
        _resource_tracker.unregister_resource(connection_name)

@asynccontextmanager
async def scroll_context_manager(
    es_client,
    scroll_id: str,
    scroll_name: str = "default_scroll"
) -> AsyncGenerator[str, None]:
    """
    Context manager for Elasticsearch scroll operations with guaranteed cleanup
    """
    async def cleanup_scroll():
        try:
            if scroll_id:
                await es_client.clear_scroll(scroll_id=scroll_id)
                logger.debug(f"Scroll {scroll_name} cleared")
        except Exception as e:
            logger.error(f"Failed to clear scroll {scroll_name}: {e}")

    _resource_tracker.register_resource(
        f"scroll_{scroll_name}",
        scroll_id,
        lambda: asyncio.create_task(cleanup_scroll()),
        "elasticsearch_scroll"
    )

    try:
        yield scroll_id
    finally:
        await cleanup_scroll()
        _resource_tracker.unregister_resource(f"scroll_{scroll_name}")

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
    pool = None

    def cleanup_pool():
        if pool:
            try:
                pool.shutdown(wait=True)
                logger.debug(f"Process pool {pool_name} shutdown")
            except Exception as e:
                logger.error(f"Failed to shutdown pool {pool_name}: {e}")

    try:
        pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=initializer,
            initargs=initargs
        )

        _resource_tracker.register_resource(
            f"pool_{pool_name}",
            pool,
            cleanup_pool,
            "process_pool"
        )

        yield pool

    finally:
        cleanup_pool()
        _resource_tracker.unregister_resource(f"pool_{pool_name}")

@asynccontextmanager
async def analytics_service_context(
    service_name: str,
    es_client,
    **config
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Comprehensive context manager for analytics services
    """
    resources = {
        "es_client": es_client,
        "service_name": service_name,
        "config": config
    }

    # Track the service context
    def cleanup_service():
        logger.debug(f"Analytics service {service_name} context cleaned up")

    _resource_tracker.register_resource(
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
        _resource_tracker.unregister_resource(f"service_{service_name}")

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

    _resource_tracker.register_resource(
        f"batch_op_{operation_name}",
        {"processed": processed_batches, "failed": failed_batches},
        cleanup_operation,
        "batch_operation"
    )

    try:
        yield tracked_batch_processor
    finally:
        cleanup_operation()
        _resource_tracker.unregister_resource(f"batch_op_{operation_name}")

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
    _resource_tracker.add_cleanup_handler(handler)

def force_cleanup_all():
    """Force cleanup of all resources"""
    _resource_tracker.cleanup_all()

def get_resource_summary() -> Dict[str, Any]:
    """Get summary of all managed resources"""
    return _resource_tracker.get_resource_summary()

# Decorator for automatic resource management
def with_resource_management(resource_type: str = "function"):
    """Decorator to add automatic resource management to functions"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            func_name = f"{func.__module__}.{func.__name__}"

            def cleanup_func_resource():
                logger.debug(f"Function {func_name} completed")

            _resource_tracker.register_resource(
                func_name,
                func,
                cleanup_func_resource,
                resource_type
            )

            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                _resource_tracker.unregister_resource(func_name)

        return wrapper
    return decorator