"""
Convertit un fichier source au format "percent" (# %% / # %% [markdown]) en notebook .ipynb.
Usage : python build_notebook.py portfolio_allocation_study.py Portfolio_Allocation_Study.ipynb
"""
import sys
import re
import nbformat as nbf


def parse_percent(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    cells = []
    cur_kind, cur_buf = None, []

    def flush():
        if cur_kind is None:
            return
        src = "\n".join(cur_buf).strip("\n")
        if cur_kind == "markdown":
            # retire le préfixe "# " (ou "#") de chaque ligne de commentaire
            md = []
            for ln in cur_buf:
                if ln.startswith("# "):
                    md.append(ln[2:])
                elif ln == "#":
                    md.append("")
                else:
                    md.append(ln)
            src = "\n".join(md).strip("\n")
            if src:
                cells.append(nbf.v4.new_markdown_cell(src))
        else:
            if src.strip():
                cells.append(nbf.v4.new_code_cell(src))

    for ln in lines:
        if re.match(r"^# %% \[markdown\]", ln):
            flush(); cur_kind, cur_buf = "markdown", []
        elif re.match(r"^# %%", ln):
            flush(); cur_kind, cur_buf = "code", []
        else:
            if cur_kind is None:      # préambule éventuel avant le 1er marqueur -> code
                cur_kind = "code"
            cur_buf.append(ln)
    flush()
    return cells


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "portfolio_allocation_study.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "Portfolio_Allocation_Study.ipynb"
    nb = nbf.v4.new_notebook()
    nb.cells = parse_percent(src)
    # injecte les magics d'affichage inline en tête de la 1re cellule de code
    for c in nb.cells:
        if c.cell_type == "code":
            c.source = "%matplotlib inline\n" + c.source
            break
    nb.metadata = {
        "kernelspec": {"display_name": "Python 3 (qrt)", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    }
    with open(out, "w", encoding="utf-8") as f:
        nbf.write(nb, f)
    n_md = sum(c.cell_type == "markdown" for c in nb.cells)
    n_code = sum(c.cell_type == "code" for c in nb.cells)
    print(f"Écrit {out} : {len(nb.cells)} cellules ({n_md} markdown, {n_code} code)")


if __name__ == "__main__":
    main()
