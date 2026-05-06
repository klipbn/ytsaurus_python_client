from functools import wraps
from time import sleep
from yt.wrapper.errors import YtOperationFailedError, YtProxyUnavailable
from yt.common import YtError


class YQLGettingException(Exception):
    pass


class YQLFailedException(Exception):
    pass


class YQLUnexpectedResultException(Exception):
    pass


class YQLTimeoutException(Exception):
    pass


def retry_on_retryable_exception(retries=8, delay=2, backoff=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            final_exc = None
            current_delay = delay
            for _ in range(retries):
                try:
                    return func(*args, **kwargs)
                except YtError as exc:
                    if any(
                        [
                            isinstance(
                                exc, (YtOperationFailedError, YtProxyUnavailable)
                            ),
                            exc.is_account_limit_exceeded(),
                            exc.is_all_target_nodes_failed(),
                            exc.is_blocked_row_wait_timeout(),
                            exc.is_chunk_not_preloaded(),
                            exc.is_concurrent_operations_limit_reached(),
                            exc.is_cypress_transaction_lock_conflict(),
                            exc.is_master_communication_error(),
                            exc.is_master_disconnected(),
                            exc.is_request_queue_size_limit_exceeded(),
                            exc.is_request_rate_limit_exceeded(),
                            exc.is_request_timed_out(),
                            exc.is_row_is_blocked(),
                            exc.is_tablet_transaction_lock_conflict(),
                        ]
                    ):
                        print(f"Retry in {current_delay}s due to: {exc}")
                        final_exc = exc
                        sleep(current_delay)
                        current_delay *= backoff
                    else:
                        raise
            raise final_exc

        return wrapper

    return decorator
