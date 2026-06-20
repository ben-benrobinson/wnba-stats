"""
One-time bootstrap: runs the nightly refresh immediately to populate the DB.
Run this after deploying to EC2 to seed initial data.

  python -m scripts.bootstrap
"""

from scripts.nightly import run

if __name__ == "__main__":
    run()
