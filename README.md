# HCIE App

Streamlit interface for the [Heterocycle Isostere Explorer](https://github.com/BrennanGroup/HCIE). Draw a query molecule in the Ketcher editor, search the MoBiVic database for bioisosteres, and download results.

## Setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv venv ~/venvs/hcie
source ~/venvs/hcie/bin/activate
uv pip install -e .
```

## Run

```bash
./run
```

This runs `postinstall.py` (downloads ~244 MB of database files on first run, then skips if already present) and launches the Streamlit app.

Mark exit vectors using the R-group tool in the Ketcher editor. The app shows a live progress bar during search.

## Citation

> Holland et al. *J. Med. Chem.* https://doi.org/10.1021/acs.jmedchem.5c03118
