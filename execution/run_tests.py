
import unittest
import sys
from pathlib import Path

# Add the 'execution' directory to sys.path
sys.path.insert(0, str(Path(__file__).parent))

if __name__ == '__main__':
    # Discover and run tests
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir='.', pattern='test_*.py')
    runner = unittest.TextTestRunner()
    runner.run(suite)
