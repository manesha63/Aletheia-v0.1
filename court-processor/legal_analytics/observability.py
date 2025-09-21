"""
Observability and Monitoring Module for Legal Analytics

Provides structured logging, metrics collection, health checks, and debugging
capabilities for all legal analytics components.
"""

import logging
import time
import json
import sys
import traceback
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
import threading
from collections import deque, defaultdict
from contextlib import contextmanager
import asyncio
import psutil

# Configure structured logging
class StructuredFormatter(logging.Formatter):
    """Custom formatter for structured JSON logging"""

    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }

        # Add extra fields if present
        if hasattr(record, 'extra_fields'):
            log_data.update(record.extra_fields)

        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }

        return json.dumps(log_data, default=str)

class MetricType(Enum):
    """Types of metrics we collect"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMING = "timing"

@dataclass
class Metric:
    """Individual metric data point"""
    name: str
    type: MetricType
    value: float
    tags: Dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

@dataclass
class HealthCheckResult:
    """Result of a health check"""
    component: str
    status: str  # "healthy", "degraded", "unhealthy"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

class MetricsCollector:
    """Collects and manages metrics for the analytics framework"""

    def __init__(self, max_history: int = 1000):
        self.metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history))
        self.lock = threading.Lock()

    def record(self, metric: Metric):
        """Record a metric"""
        with self.lock:
            key = f"{metric.name}:{metric.type.value}"
            self.metrics[key].append(metric)

    def counter(self, name: str, value: float = 1, tags: Dict[str, str] = None):
        """Record a counter metric"""
        self.record(Metric(name, MetricType.COUNTER, value, tags or {}))

    def gauge(self, name: str, value: float, tags: Dict[str, str] = None):
        """Record a gauge metric"""
        self.record(Metric(name, MetricType.GAUGE, value, tags or {}))

    def timing(self, name: str, duration_seconds: float, tags: Dict[str, str] = None):
        """Record a timing metric"""
        self.record(Metric(name, MetricType.TIMING, duration_seconds, tags or {}))

    @contextmanager
    def timer(self, name: str, tags: Dict[str, str] = None):
        """Context manager to time operations"""
        start = time.time()
        try:
            yield
        finally:
            duration = time.time() - start
            self.timing(name, duration, tags)

    def get_metrics_summary(self, since_minutes: int = 5) -> Dict[str, Any]:
        """Get summary of recent metrics"""
        cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)
        summary = {}

        with self.lock:
            for key, metrics_deque in self.metrics.items():
                recent_metrics = [m for m in metrics_deque if m.timestamp > cutoff]

                if not recent_metrics:
                    continue

                name, metric_type = key.rsplit(':', 1)
                values = [m.value for m in recent_metrics]

                if metric_type == MetricType.COUNTER.value:
                    summary[key] = {
                        "type": metric_type,
                        "total": sum(values),
                        "count": len(values),
                        "rate_per_minute": sum(values) / max(1, since_minutes)
                    }
                elif metric_type == MetricType.GAUGE.value:
                    summary[key] = {
                        "type": metric_type,
                        "current": values[-1] if values else None,
                        "min": min(values),
                        "max": max(values),
                        "avg": sum(values) / len(values)
                    }
                elif metric_type == MetricType.TIMING.value:
                    summary[key] = {
                        "type": metric_type,
                        "count": len(values),
                        "min_seconds": min(values),
                        "max_seconds": max(values),
                        "avg_seconds": sum(values) / len(values),
                        "p95_seconds": self._percentile(values, 0.95),
                        "p99_seconds": self._percentile(values, 0.99)
                    }

        return summary

    def _percentile(self, values: List[float], percentile: float) -> float:
        """Calculate percentile of values"""
        if not values:
            return 0
        sorted_values = sorted(values)
        index = int(len(sorted_values) * percentile)
        return sorted_values[min(index, len(sorted_values) - 1)]

class HealthChecker:
    """Manages health checks for analytics components"""

    def __init__(self):
        self.checks: Dict[str, Callable] = {}
        self.last_results: Dict[str, HealthCheckResult] = {}
        self.lock = threading.Lock()

    def register_check(self, component: str, check_func: Callable):
        """Register a health check function for a component"""
        with self.lock:
            self.checks[component] = check_func

    async def run_checks(self) -> Dict[str, HealthCheckResult]:
        """Run all registered health checks"""
        results = {}

        for component, check_func in self.checks.items():
            try:
                # Support both sync and async check functions
                if asyncio.iscoroutinefunction(check_func):
                    result = await check_func()
                else:
                    result = check_func()

                if isinstance(result, HealthCheckResult):
                    results[component] = result
                else:
                    # Convert boolean/dict results to HealthCheckResult
                    if isinstance(result, bool):
                        status = "healthy" if result else "unhealthy"
                        message = f"{component} is {status}"
                        results[component] = HealthCheckResult(component, status, message)
                    elif isinstance(result, dict):
                        results[component] = HealthCheckResult(
                            component,
                            result.get("status", "unknown"),
                            result.get("message", ""),
                            result.get("details", {})
                        )

            except Exception as e:
                results[component] = HealthCheckResult(
                    component,
                    "unhealthy",
                    f"Health check failed: {str(e)}",
                    {"error": str(e)}
                )

        with self.lock:
            self.last_results = results

        return results

    def get_overall_status(self) -> str:
        """Get overall system health status"""
        with self.lock:
            if not self.last_results:
                return "unknown"

            statuses = [r.status for r in self.last_results.values()]

            if all(s == "healthy" for s in statuses):
                return "healthy"
            elif any(s == "unhealthy" for s in statuses):
                return "unhealthy"
            else:
                return "degraded"

class PerformanceTracker:
    """Tracks performance metrics for operations"""

    def __init__(self, metrics_collector: MetricsCollector):
        self.metrics = metrics_collector
        self.active_operations: Dict[str, float] = {}
        self.lock = threading.Lock()

    @contextmanager
    def track_operation(self, operation: str, metadata: Dict[str, Any] = None):
        """Track the performance of an operation"""
        operation_id = f"{operation}_{id(self)}_{time.time()}"

        # Record start
        with self.lock:
            self.active_operations[operation_id] = time.time()

        self.metrics.counter(f"operations.{operation}.started")

        try:
            yield operation_id
            # Success
            self.metrics.counter(f"operations.{operation}.completed")

        except Exception as e:
            # Failure
            self.metrics.counter(f"operations.{operation}.failed", tags={"error": type(e).__name__})
            raise

        finally:
            # Record duration
            with self.lock:
                if operation_id in self.active_operations:
                    start_time = self.active_operations.pop(operation_id)
                    duration = time.time() - start_time
                    self.metrics.timing(f"operations.{operation}.duration", duration)

class ObservabilityManager:
    """Central manager for all observability features"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.metrics = MetricsCollector()
            self.health = HealthChecker()
            self.performance = PerformanceTracker(self.metrics)
            self.logger = self._setup_logger()
            self.initialized = True

            # Register default health checks
            self._register_default_health_checks()

    def _setup_logger(self) -> logging.Logger:
        """Setup structured logging"""
        logger = logging.getLogger("legal_analytics")
        logger.setLevel(logging.INFO)

        # Remove existing handlers
        logger.handlers = []

        # Add structured JSON handler
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)

        return logger

    def _register_default_health_checks(self):
        """Register default system health checks"""

        def check_memory():
            memory = psutil.virtual_memory()
            if memory.percent > 90:
                return HealthCheckResult("memory", "unhealthy", f"Memory usage critical: {memory.percent}%")
            elif memory.percent > 75:
                return HealthCheckResult("memory", "degraded", f"Memory usage high: {memory.percent}%")
            else:
                return HealthCheckResult("memory", "healthy", f"Memory usage normal: {memory.percent}%")

        def check_cpu():
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > 90:
                return HealthCheckResult("cpu", "unhealthy", f"CPU usage critical: {cpu_percent}%")
            elif cpu_percent > 75:
                return HealthCheckResult("cpu", "degraded", f"CPU usage high: {cpu_percent}%")
            else:
                return HealthCheckResult("cpu", "healthy", f"CPU usage normal: {cpu_percent}%")

        self.health.register_check("memory", check_memory)
        self.health.register_check("cpu", check_cpu)

    def log(self, level: str, message: str, **kwargs):
        """Log with structured fields"""
        extra_fields = kwargs
        record = self.logger.makeRecord(
            self.logger.name,
            getattr(logging, level.upper()),
            "",  # pathname
            0,   # lineno
            message,
            (),  # args
            None  # exc_info
        )
        record.extra_fields = extra_fields
        self.logger.handle(record)

    async def get_diagnostics(self) -> Dict[str, Any]:
        """Get comprehensive diagnostics information"""
        health_results = await self.health.run_checks()
        metrics_summary = self.metrics.get_metrics_summary()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "health": {
                "overall_status": self.health.get_overall_status(),
                "checks": {k: asdict(v) for k, v in health_results.items()}
            },
            "metrics": metrics_summary,
            "system": {
                "cpu_count": psutil.cpu_count(),
                "memory_total_gb": psutil.virtual_memory().total / (1024**3),
                "memory_available_gb": psutil.virtual_memory().available / (1024**3),
                "cpu_percent": psutil.cpu_percent(interval=1),
                "active_operations": len(self.performance.active_operations)
            }
        }

# Global observability instance
_observability = ObservabilityManager()

# Convenience functions
def get_observability() -> ObservabilityManager:
    """Get the global observability manager"""
    return _observability

def log_info(message: str, **kwargs):
    """Log info message with structured fields"""
    _observability.log("info", message, **kwargs)

def log_error(message: str, **kwargs):
    """Log error message with structured fields"""
    _observability.log("error", message, **kwargs)

def log_warning(message: str, **kwargs):
    """Log warning message with structured fields"""
    _observability.log("warning", message, **kwargs)

def record_metric(name: str, value: float, metric_type: str = "counter", tags: Dict[str, str] = None):
    """Record a metric"""
    if metric_type == "counter":
        _observability.metrics.counter(name, value, tags)
    elif metric_type == "gauge":
        _observability.metrics.gauge(name, value, tags)
    elif metric_type == "timing":
        _observability.metrics.timing(name, value, tags)

@contextmanager
def track_operation(operation: str, metadata: Dict[str, Any] = None):
    """Track an operation's performance"""
    with _observability.performance.track_operation(operation, metadata) as op_id:
        yield op_id

def register_health_check(component: str, check_func: Callable):
    """Register a health check for a component"""
    _observability.health.register_check(component, check_func)

async def get_diagnostics() -> Dict[str, Any]:
    """Get system diagnostics"""
    return await _observability.get_diagnostics()

# Decorators for easy integration
def observe_function(operation_name: Optional[str] = None):
    """Decorator to add observability to functions"""
    def decorator(func):
        name = operation_name or f"{func.__module__}.{func.__name__}"

        async def async_wrapper(*args, **kwargs):
            with track_operation(name):
                try:
                    result = await func(*args, **kwargs)
                    log_info(f"Operation completed: {name}")
                    return result
                except Exception as e:
                    log_error(f"Operation failed: {name}", error=str(e), error_type=type(e).__name__)
                    raise

        def sync_wrapper(*args, **kwargs):
            with track_operation(name):
                try:
                    result = func(*args, **kwargs)
                    log_info(f"Operation completed: {name}")
                    return result
                except Exception as e:
                    log_error(f"Operation failed: {name}", error=str(e), error_type=type(e).__name__)
                    raise

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator