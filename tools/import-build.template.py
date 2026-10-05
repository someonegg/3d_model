"""Copy imported source assets into the model build workspace."""
from pathlib import Path
import os
import shutil


def main():
    source = Path(__file__).resolve().parents[1] / 'source'
    output = Path(os.environ['MODEL_OUTPUT_DIR'])
    shutil.copytree(source, output, dirs_exist_ok=True)


if __name__ == '__main__':
    main()
