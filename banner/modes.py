from enum import Enum


class RunMode(str, Enum):
    TEST = "test"
    PROD = "prod"
    DEBUG = "debug"