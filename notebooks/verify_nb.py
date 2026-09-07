import sys
import nbformat as nbf

nb = nbf.read(sys.argv[1] if len(sys.argv) > 1 else "Portfolio_Allocation_Study.ipynb", as_version=4)
n_img = n_err = n_text = n_code = 0
errors = []
for i, c in enumerate(nb.cells):
    if c.cell_type != "code":
        continue
    n_code += 1
    for o in c.get("outputs", []):
        if o.get("output_type") == "error":
            n_err += 1
            errors.append((i, o.get("ename"), " ".join(o.get("traceback", []))[-300:]))
        data = o.get("data", {})
        if "image/png" in data or "image/svg+xml" in data:
            n_img += 1
        if "text/plain" in data or o.get("output_type") == "stream":
            n_text += 1

print(f"cellules code    : {n_code}")
print(f"figures (images) : {n_img}")
print(f"sorties texte    : {n_text}")
print(f"ERREURS          : {n_err}")
for i, name, tb in errors:
    print(f"  ! cell {i}: {name} :: ...{tb}")
print("STATUS:", "OK" if n_err == 0 else "HAS_ERRORS")
