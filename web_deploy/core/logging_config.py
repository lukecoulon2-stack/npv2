import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def get_file_logger(log_dir=None):
    directory = Path(log_dir) if log_dir else Path.home() / ".web_deploy_kit" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"web_deploy.file.{directory.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        log_path = directory / "web-deployer.log"
        handler = RotatingFileHandler(
            log_path,
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        if os.name != "nt":
            os.chmod(log_path, 0o600)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)

    return logger