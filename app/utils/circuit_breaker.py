"""Circuit breaker pattern for preventing cascading failures."""

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Possible states of a circuit breaker."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing fast, rejecting requests
    HALF_OPEN = "half_open"  # Testing if the service is back


class CircuitBreaker:
    """
    Circuit breaker implementation for handling service degradation gracefully.
    
    States:
    - CLOSED: Normal operation. Requests pass through. Failures are counted.
    - OPEN: Too many failures detected. Requests fail immediately without calling service.
    - HALF_OPEN: Testing if service recovered. One request passes through.
    
    Configuration:
    - failure_threshold: Number of failures before opening circuit (default: 5)
    - recovery_timeout: Seconds before transitioning from OPEN to HALF_OPEN (default: 30)
    - success_threshold: Number of successes in HALF_OPEN before closing (default: 2)
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        success_threshold: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.opened_at: Optional[float] = None
    
    def _should_attempt_reset(self) -> bool:
        """Check if we should try to recover from OPEN state."""
        if self.state != CircuitState.OPEN:
            return False
        
        if self.opened_at is None:
            return False
        
        elapsed = time.time() - self.opened_at
        return elapsed >= self.recovery_timeout
    
    async def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """
        Execute a function through the circuit breaker.
        
        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments
        
        Returns:
            Result of the function call
        
        Raises:
            Exception: If circuit is open or function fails
        """
        # Check if we should transition to HALF_OPEN
        if self._should_attempt_reset():
            self.state = CircuitState.HALF_OPEN
            self.success_count = 0
            logger.info(f"Circuit '{self.name}' transitioning to HALF_OPEN")
        
        # If circuit is OPEN and not yet time to retry, fail fast
        if self.state == CircuitState.OPEN:
            raise Exception(
                f"Circuit '{self.name}' is OPEN. Service is degraded. "
                f"Failing fast to prevent overload."
            )
        
        # Try to execute the function
        try:
            result = await func(*args, **kwargs)
            
            # Success! Handle state transitions
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                logger.info(
                    f"Circuit '{self.name}' HALF_OPEN success "
                    f"({self.success_count}/{self.success_threshold})"
                )
                
                if self.success_count >= self.success_threshold:
                    # Service recovered! Close the circuit
                    self._close()
            elif self.state == CircuitState.CLOSED:
                # Reset failure count on success
                if self.failure_count > 0:
                    self.failure_count = 0
                    logger.debug(f"Circuit '{self.name}' failure count reset")
            
            return result
        
        except Exception as e:
            # Handle failure
            self.last_failure_time = time.time()
            self.failure_count += 1
            
            logger.warning(
                f"Circuit '{self.name}' failure #{self.failure_count}/{self.failure_threshold}: {e}"
            )
            
            if self.state == CircuitState.HALF_OPEN:
                # Failure during recovery attempt - reopen circuit
                self._open()
                raise Exception(
                    f"Circuit '{self.name}' HALF_OPEN attempt failed. Reopening."
                ) from e
            
            elif self.failure_count >= self.failure_threshold:
                # Too many failures - open circuit
                self._open()
                raise Exception(
                    f"Circuit '{self.name}' opened after {self.failure_threshold} failures"
                ) from e
            
            # Still in CLOSED state, just propagate the error
            raise
    
    def _open(self):
        """Transition circuit to OPEN state."""
        self.state = CircuitState.OPEN
        self.opened_at = time.time()
        logger.error(f"Circuit '{self.name}' is now OPEN. Rejecting requests.")
    
    def _close(self):
        """Transition circuit to CLOSED state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.opened_at = None
        logger.info(f"Circuit '{self.name}' is now CLOSED. Service recovered.")
    
    def get_state(self) -> dict[str, Any]:
        """Get current circuit state for monitoring."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time,
            "opened_at": self.opened_at,
        }


# Global circuit breaker for database operations
_db_circuit_breaker: Optional[CircuitBreaker] = None


def get_db_circuit_breaker() -> CircuitBreaker:
    """Get or create the global database circuit breaker."""
    global _db_circuit_breaker
    if _db_circuit_breaker is None:
        _db_circuit_breaker = CircuitBreaker(
            name="database",
            failure_threshold=5,
            recovery_timeout=30,
            success_threshold=2,
        )
    return _db_circuit_breaker
