import logging
import sys
import structlog
from app.core.config import settings


def setup_logging():
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


setup_logging()
logger = structlog.get_logger("privacy_workbench")


def log_llm_run(**fields):
    """AI-workflow log line: stage, prompt_version, model, input_hash, valid_output, retries, fallback_used, tokens, latency."""
    logger.info("llm_run", component="llm_run", **fields)


def log_tool_call(**fields):
    logger.info("tool_call", component="tool_call", **fields)


def log_approval(**fields):
    logger.info("approval", component="approval", **fields)


def log_action(**fields):
    logger.info("action", component="action", **fields)
