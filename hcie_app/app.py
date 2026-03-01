import multiprocessing
import os
import re
import sys
import tempfile
import time
import subprocess

import streamlit as st
import pandas as pd
from hcie import DatabaseSearch
from hcie.database_search import load_database, print_results, alignments_to_sdf, mols_to_image

from streamlit_ketcher import st_ketcher


def normalize_smiles(smiles: str) -> str:
    """Convert Ketcher SMILES output to canonical SMILES with [R] for HCIE.

    Ketcher may emit CXSMILES extensions, numbered R-group labels, or messy
    ring-closure notation for dummy atoms.  This function canonicalizes via
    RDKit and outputs clean SMILES with ``[R]`` exit-vector markers.
    """
    if not smiles:
        return ""
    from rdkit import Chem

    # Strip CXSMILES extension block (everything from " |" onward)
    base = smiles.split(" |")[0].strip()
    # Normalize all R-group / dummy variants to [*] so RDKit can parse
    base = re.sub(r"\[R\d*\]", "[*]", base)
    base = re.sub(r"\[\*:\d+\]", "[*]", base)
    mol = Chem.MolFromSmiles(base)
    if mol is None:
        return base
    # Canonicalize, then convert dummy atoms to [R] for HCIE
    return Chem.MolToSmiles(mol).replace("*", "[R]")


st.set_page_config(page_title="HCIE - Heterocycle Isostere Explorer", layout="wide")

st.title("Heterocycle Isostere Explorer")
st.markdown(
    "Identify novel aromatic heterocyclic bioisosteres using shape and "
    "electrostatic similarity. Draw a query molecule below and mark "
    "attachment points (exit vectors) using the R-group tool."
)

# --- Molecule Input ---
st.subheader("Query Molecule")

initial_smiles = st.session_state.get("smiles", "")
raw_smiles = st_ketcher(initial_smiles, height=600, key="ketcher")
active_smiles = normalize_smiles(raw_smiles)
if active_smiles:
    st.session_state["smiles"] = active_smiles

# --- Query feedback ---
if active_smiles:
    st.info(f"**Query SMILES:** `{active_smiles}`")
else:
    st.warning("Draw a molecule above to set the query.")

# --- Search ---
mol_name = st.text_input(
    "Query name",
    value=st.session_state.get("mol_name", "query"),
    help="Label used for output file names.",
)

has_exit_vector = active_smiles and ("[R]" in active_smiles or "*" in active_smiles)
run_search = st.button("Run Search", type="primary", disabled=not active_smiles)

if run_search and active_smiles and not has_exit_vector:
    st.error(
        "The query molecule has no exit vectors. "
        "Mark at least one attachment point using the R-group tool "
        "in the editor before searching."
    )

if run_search and active_smiles and has_exit_vector:
    name = mol_name or "query"

    with st.status(f"Searching for bioisosteres of **{name}**…", expanded=True) as status:
        progress_bar = st.progress(0, text="Loading database…")
        start = time.time()

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_dir = os.getcwd()
            try:
                os.chdir(tmpdir)
                search = DatabaseSearch(active_smiles, name=name)

                with multiprocessing.Manager() as manager:
                    database_by_regid = manager.dict(load_database())
                    elapsed = time.time() - start
                    progress_bar.progress(0, text=f"Database loaded ({elapsed:.0f}s). Aligning molecules…")

                    if search.search_type == "vector":
                        task_args = search.generate_single_vector_tasks(database_by_regid)
                        total = len(task_args)
                        chunksize = max(1, total // 200)
                        results = []
                        with multiprocessing.Pool() as pool:
                            for result in pool.imap_unordered(
                                search.align_and_score_probe_by_vector_wrapper,
                                task_args,
                                chunksize=chunksize,
                            ):
                                results.append(result)
                                if len(results) % chunksize == 0 or len(results) == total:
                                    pct = len(results) / total
                                    elapsed = time.time() - start
                                    progress_bar.progress(
                                        pct,
                                        text=f"Aligned {len(results):,}/{total:,} molecules ({elapsed:.0f}s)",
                                    )

                    elif search.search_type == "hash":
                        search.database_vector_matches = search.get_exit_vectors_for_hash_matches(
                            database_by_regid
                        )
                        task_args = [
                            (match_regid, vector_pairs, database_by_regid)
                            for match_regid, vector_pairs in search.database_vector_matches.items()
                        ]
                        total = len(task_args)
                        chunksize = max(1, total // 200)
                        results = []
                        with multiprocessing.Pool() as pool:
                            for result in pool.imap_unordered(
                                search.align_and_score_molecule_wrapper,
                                task_args,
                                chunksize=chunksize,
                            ):
                                results.append(result)
                                if len(results) % chunksize == 0 or len(results) == total:
                                    pct = len(results) / total
                                    elapsed = time.time() - start
                                    progress_bar.progress(
                                        pct,
                                        text=f"Aligned {len(results):,}/{total:,} matches ({elapsed:.0f}s)",
                                    )
                    else:
                        raise ValueError("Search type not supported")

                # Post-process results (same as HCIE internals)
                processed_mols = {r[0]: r[-1] for r in results}
                results = sorted([r[:-1] for r in results], key=lambda x: x[1], reverse=True)

                progress_bar.progress(1.0, text="Writing results…")
                search.results_to_file(results, processed_mols)

            finally:
                os.chdir(orig_dir)

            results_dir = os.path.join(tmpdir, f"{name}_hcie_results")
            csv_path = os.path.join(results_dir, f"{name}_results.csv")
            png_path = os.path.join(results_dir, f"{name}_results.png")
            sdf_path = os.path.join(results_dir, f"{name}_aligned_results.sdf")

            # Store results in session state so they persist after rerun
            st.session_state["results_name"] = name
            if os.path.exists(csv_path):
                st.session_state["results_csv"] = open(csv_path, "r").read()
                try:
                    df = pd.read_csv(csv_path, skiprows=6)
                    st.session_state["results_df"] = df
                except Exception:
                    st.session_state["results_df"] = None

            if os.path.exists(png_path):
                st.session_state["results_png"] = open(png_path, "rb").read()

            if os.path.exists(sdf_path):
                st.session_state["results_sdf"] = open(sdf_path, "rb").read()

        elapsed = time.time() - start
        progress_bar.empty()
        status.update(label=f"Search complete in {elapsed:.0f}s", state="complete", expanded=True)

# --- Display Results ---
if "results_df" in st.session_state and st.session_state["results_df"] is not None:
    st.subheader("Results")
    st.dataframe(st.session_state["results_df"], use_container_width=True, height=400)

if "results_png" in st.session_state:
    st.subheader("Top Molecules")
    st.image(st.session_state["results_png"], use_container_width=True)

# Downloads
dl_name = st.session_state.get("results_name", "query")
dl_col1, dl_col2 = st.columns(2)
with dl_col1:
    if "results_csv" in st.session_state:
        st.download_button(
            "Download CSV",
            data=st.session_state["results_csv"],
            file_name=f"{dl_name}_results.csv",
            mime="text/csv",
        )
with dl_col2:
    if "results_sdf" in st.session_state:
        st.download_button(
            "Download SDF",
            data=st.session_state["results_sdf"],
            file_name=f"{dl_name}_aligned_results.sdf",
            mime="chemical/x-mdl-sdfile",
        )


def main():
    """Entry point for the hcie-app console script."""
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", __file__] + sys.argv[1:],
        check=True,
    )


# Only launch a new Streamlit server when invoked from the command line,
# NOT when Streamlit is already executing this script.
if __name__ == "__main__":
    from streamlit import runtime

    if not runtime.exists():
        main()
