"""Common CLI wrapper for the step-1 scripts."""
import argparse
import glob
import logging
import os
import warnings

from .config import RAW, STG

warnings.filterwarnings("ignore", category=UserWarning)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def args(description, folder):
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--raw-dir", default=os.path.join(RAW, folder))
    ap.add_argument("--out-dir", default=STG)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    a.files = sorted(f for f in glob.glob(os.path.join(a.raw_dir, "*.xlsx"))
                     if not os.path.basename(f).startswith("~$"))
    return a
