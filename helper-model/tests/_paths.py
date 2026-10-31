import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # helper-model/
if HERE not in sys.path:
    sys.path.insert(0, HERE)
APP = os.path.join(os.path.dirname(HERE), "app")
