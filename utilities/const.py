#!/usr/bin/env python
"""Constants."""
import numpy as np

# MISC
COLORS = dict(
    HEADER='\033[95m',
    OKBLUE='\033[94m',
    OKGREEN='\033[92m',
    WARNING='\033[93m',
    FAIL='\033[91m',
    ENDC='\033[0m',
    BOLD='\033[1m',
    UNDERLINE='\033[4m',
    GREEN='\u001b[32m',
    ORANGE="\033[33m"
)

QUALITATIVE_COLOR_PALETTE = [
    "#1D6996",
    "#CC503E",
    "#73AF48",
    "#0F8554",
    "#E17C05",
    "#38A6A5",
    "#EDAD08",
    "#94346E",
    "#5F4690",
    "#6F4070",
    "#994E95",
    "#666666"
]

#5F4690,#1D6996,#38A6A5,#0F8554,#73AF48,#EDAD08,#E17C05,#CC503E,#94346E,#6F4070,#994E95,#666666

# MISC
MIN_STAT_EPS = 5

# STORAGE
BASE_SAVE_PATH = "storage/saved_models/states/"
STORAGE_DIR = "storage/experience/"
PRETRAINED_COMPONENTS_PATH = "storage/pretrained/"
PATH_TO_EXPERIMENTS = "monitor/static/experiments/"
PATH_TO_BENCHMARKS = "docs/benchmarks/"

# NUMERICAL PRECISION
NP_FLOAT_PREC = np.float64
NUMPY_INTEGER_PRECISION = np.int64
EPS = 1e-8

# SHAPES
VISION_WH = 227

# DEBUGGING
DETERMINISTIC = False
DEBUG = False
