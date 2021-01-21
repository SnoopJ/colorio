import json
import pathlib

from ..helpers import ColorDifferenceDataset


class Witt(ColorDifferenceDataset):
    def __init__(self):
        this_dir = pathlib.Path(__file__).resolve().parent

        with open(this_dir / "witt.json") as f:
            data = json.load(f)

        super().__init__("Witt", data["dv"], data["pairs"])
